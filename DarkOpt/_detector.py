from _TES import TES
from _QET import QET
from MaterialProperties import TESMaterial, DetectorMaterial, QETMaterial
import numpy as np
import scipy.constants as constants
import qetpy as qp
import matplotlib.pyplot as plt
from matplotlib import rcParams

#import matplotlib.colors as mcolors
from matplotlib import cm  

nice_fonts = {
        # Use LaTeX to write all text
        #"text.usetex": True,
        "font.family": "serif",
        # Use 10pt font in plots, to match 10pt font in document
        "axes.labelsize": 14,
        "font.size": 12,
        # Make the legend/label fonts a little smaller
        "legend.fontsize": 12,
        "xtick.labelsize": 12,
        "ytick.labelsize": 12,
}

rcParams.update(nice_fonts)



class Detector:

    def __init__(self, name, absorber, QET, passive=1, n_channel=1, 
                freqs=np.linspace(.1, 1e6, int(1e5))):
        
        """
        :param name: Detector Name
        :param fridge: Fridge in which detector is in
        :param absorber: Absorbing part of detector
        :param n_channel: Number of channels
        :param NQET.TES: Number of TES on detector
        :param lQET.TES: Length of TES
        :param l_fin: Length of QET Fin
        :param h_fin: Height of QET Fin
        :param l_overlap: Length of Overlap of W and Al???

        """
        # Width of Main Bias Rails and QET Rails 
        self._w_rail_main = 6e-6
        self._w_railQET = 3e-6 

        self._name = name
        self._absorber = absorber
        self._n_channel = n_channel
        self._l_fin = QET.l_fin
        self._h_fin = QET.h_fin
        self._l_overlap = QET.TES.l_overlap
        self._sigma_energy = 0
        self.QET = QET 
        tes = QET.TES
        self.freqs = freqs
        self.eres = None


        # ------------- QET Fins ----------------------------------------------
        # Surface area covered by QET Fins 
        self._SA_active = n_channel * tes.nTES * QET.a_fin

        # Average area per cell, and corresponding length
        a_cell = self._absorber.get_pattern_SA() / (n_channel * tes.nTES) # 1/2 channels on each side
       
        QET_block = (2*QET.l_fin + tes.l)*(2*QET.l_fin) 
        if QET_block*tes.nTES > self._absorber.get_pattern_SA(): 
            #print("----- ERROR: Invalid Design - QET cells don't fit.")
            self._cells_fit = False
        else: self._cells_fit = True
        
        self._l_cell = np.sqrt(a_cell)
        self._w_cell = np.sqrt(a_cell/2) # hypothetical optimum but only gives a couple percent decrease in passive Al
        self._h_cell = 2*self._w_cell

        y_cell = 2 * QET.l_fin + tes.l # length QET 
        
        if self._l_cell > y_cell:
            #print("---- Not Close Packed")
            # Design is not close packed. Get passive Al/QET
            a_passiveQET = self._l_cell * self._w_rail_main + (self._l_cell - y_cell) * self._w_railQET
            self._close_packed = False
        else:
            #print("---- Close Packed")
            # Design is close packed. No vertical rail to QET
            x_cell = a_cell / y_cell
            a_passiveQET = x_cell * self._w_rail_main
            self._close_packed = True
        
        tes_passive = a_passiveQET * n_channel * tes.nTES
        
        # Passive Al Rails for PD2 Like Layout
        outer_ring = 2 * np.pi * (self._absorber.get_R() - self._absorber.get_w_safety()) * self._w_rail_main
        inner_ring = outer_ring / (np.sqrt(2))
        inner_vertical_rail = 3 * (self._absorber.get_R() - self._absorber.get_w_safety()) * self._w_rail_main * (1 - np.sqrt(2)/2.0)
        outer_vertical_rail = (self._absorber.get_R() - self._absorber.get_w_safety()) * self._w_rail_main * (1 + np.sqrt(2)/2.0)

        # Calc Alignment Mark Passive Area 
        one_alignment_window = 20772e-12 
        total_alignment = 5*one_alignment_window
        self.total_alignment = total_alignment
        #total_alignment = 0.0

        # Total Passive Surface Area
        # 1. TES Passive Area
        # 2. Outer Ring
        # 3. Inner Ring
        # 4. Inner Vertical Rail
        # 5. Outer Vertical Rail
        # 6. Alignment Marks
        if absorber._shape == "cylinder": # Indicates PD2-like Rail Layout
            self._SA_passive = tes_passive + outer_ring + inner_ring + inner_vertical_rail + outer_vertical_rail + total_alignment
        if absorber._shape == "square": # New Square Rail Layout Design
            if passive == 1:
                self._SA_passive = tes_passive + 2*(self._absorber._r - 2*self._absorber._w_safety)*self._w_rail_main + 2*one_alignment_window
            elif passive == 0:            
                self._SA_passive = 0 # FOR THEORETICAL UNDERSTANDING, DELETE  
        
        # Fraction of surface area which has phonon absorbing aluminum
        self._fSA_qpabsorb = (self._SA_passive + self._SA_active) / self._absorber.get_SA()

        # Fraction of Al which is QET fin which can produce signal
        self._ePcollect = self._SA_active / (self._SA_active + self._SA_passive)
 
        PD2_absb_time = 20e-6
        absb_lscat = absorber.scattering_length()
        PD2_fSA_qpabsb = 0.0214 # percentage of total surface area 
        PD2_lscat = 0.0019488

        #print("-- -- Phonon Absorption Time -- --")
        #print("      PD2 Abs Time:    ", PD2_absb_time)
        #print("      PD2 Scat Length: ", PD2_lscat)
        #print("      PD2 fSA QP Absb: ", PD2_fSA_qpabsb)
        #print("      Scat Length      ", absb_lscat)
        #print("      fSA WP Absb      ", self._fSA_qpabsorb)
        
        # Scale collection time based of PD2 time. Where does this come from?
        self._t_pabsb = PD2_absb_time * (absb_lscat / PD2_lscat) * (PD2_fSA_qpabsb / self._fSA_qpabsorb)

        self._w_collect = 1/self._t_pabsb

        # ------------ Total Phonon Collection Efficiency -------------

        # The loss mechanisms in our detector are:
        # 1) subgap downconversion of athermal phonons in the crystal
        # 2) collection of athermal phonons by passive metal on the surface of our detector ( Det.ePcollect)
        # 3) Efficiency of QP production in Al fin (QET.ePQP)
        # 4) Efficiency of QP transport to TES (QET.eQPabsb)
        # 5) Energy conversion efficiency at W/Al interface
        # 6) ?

        # Phonon Downconversion Factor
        self._e_downconvert = 1/1000 
        self._e_downconvert = 1/4000

        aluminum = QETMaterial("Al")

        pE_thresh = 2*1.76*constants.k*aluminum._Tc
        p_baresurface = (self._absorber.get_SA() - self._SA_active - self._SA_passive)/self._absorber.get_SA()
        p_subgap = p_baresurface**3000
        p_notsubgap = 1-p_subgap
        
        # Let's combine 1), 5), and 6) together and assume that it is the same as the measured/derived value from iZIP4
        self._e156 = 0.8690 # should scale with Al coverage.... 

        # Total collection efficiency:
        self._eEabsb = self._e156 * self._ePcollect * self.QET.eQPabsb * self.QET.ePQP # * self._e_downconvert * self._fSA_qpabsorb 
        
        self.fSA_active = self._SA_active/self._absorber.get_SA()
        self.fSA_passive = self._SA_passive/self._absorber.get_SA()

        # ------------ Thermal Conductance to Bath ---------------
        self._kpb = 1.55e-4 #### where did this come from/does it even do anything?
        # Thermal conductance coefficient between detector and bath
        self._nkpb = 4

        #Simulate noise
        self.noise = qp.sim.TESnoise(freqs=self.freqs,
                                     rload=tes.rl,
                                     r0=tes.r0,
                                     rshunt=tes.rsh,
                                     beta=tes.beta,
                                     loopgain=tes.LG,
                                     inductance=tes.L,
                                     tau0=tes.tau0,
                                     G=tes.Gep,
                                     qetbias=tes.vbias/tes.rsh,
                                     tc=tes.t0,
                                     tload=tes.tload,
                                     tbath=tes.t_mc,
                                     n=tes.n,
                                     )
        
    def calc_res(self):
        eres = qp.sim.energy_res_estimate(self.freqs, 
                                          self._t_pabsb, 
                                          self.noise.s_ptot(),
                                          self._eEabsb)
        self.eres = eres
        return self.eres
    
    def plot_si(self, figsize=(6.75, 4.455), xlims=None, ylims=None):
        noise = self.noise
        f = self.freqs
        
        s_ielec = noise.s_isquid()
        s_itfn = noise.s_itfn()
        s_ites = noise.s_ites()
        s_iload = noise.s_iload()
        s_itot = noise.s_itot()
  
        cmap = 'viridis'
        cmap = cm.get_cmap(cmap)
        cs = cmap(np.linspace(0, 1,5))
       
        fig, ax = plt.subplots(figsize=figsize)

        ax.plot(f, np.sqrt(s_itfn), color=cs[3],
               linewidth=1.8, label='TFN', zorder = 30, linestyle='-')
        
        ax.plot(f, np.sqrt(s_ites), color=cs[1],
               linewidth=1.8, label='TES', zorder = 10, linestyle='-')
        
        ax.plot(f, np.sqrt(s_iload), color=cs[0],
               linewidth=1.8, label='Load', zorder = 20, linestyle=':')
        ax.plot(f, np.sqrt(s_ielec),  color=cs[4],
               linewidth=1.8, label='Electronics', zorder = 5, linestyle='--')
        ax.plot(f, np.sqrt(s_itot), color='k',
               linewidth=1.8, label='Total', zorder = 200, linestyle='-')
        ax.set_ylabel(r'Current Noise [A/$\sqrt{\mathrm{Hz}}$]')
        ax.tick_params(which="both", direction="in", right=True, top=True, zorder=300)
        ax.set_xlabel(r'Frequency [Hz]')
        ax.set_yscale('log')
        ax.set_xscale('log')
        plt.grid(True, alpha=.5, linestyle='--')
        if xlims is not None:
            ax.set_xlim(xlims)
        if ylims is not None:
            ax.set_ylim(ylims)
        plt.legend(facecolor='white', framealpha=1)
        ax.set_title('Current Referenced Noise')
        fig.tight_layout()
        
    def plot_sp(self, figsize=(6.75, 4.455), xlims=None, ylims=None):
        noise = self.noise
        f = self.freqs
        
        s_pelec = noise.s_psquid()
        s_ptfn = noise.s_ptfn()
        s_ptes = noise.s_ptes()
        s_pload = noise.s_pload()
        s_ptot = noise.s_ptot()

        cmap = 'viridis'
        cmap = cm.get_cmap(cmap)
        cs = cmap(np.linspace(0, 1,5))
       
        fig, ax = plt.subplots(figsize=figsize)

        ax.plot(f, np.sqrt(s_ptfn), color=cs[3],
               linewidth=1.8, label='TFN', zorder = 30, linestyle='-')
        
        ax.plot(f, np.sqrt(s_ptes), color=cs[1],
               linewidth=1.8, label='TES', zorder = 10, linestyle='-')
        
        ax.plot(f, np.sqrt(s_pload), color=cs[0],
               linewidth=1.8, label='Load', zorder = 20, linestyle=':')
        ax.plot(f, np.sqrt(s_pelec),  color=cs[4],
               linewidth=1.8, label='Electronics', zorder = 5, linestyle='--')
        ax.plot(f, np.sqrt(s_ptot), color='k',
               linewidth=1.8, label='Total', zorder = 200, linestyle='-')
        ax.set_ylabel(r'NEP [W/$\sqrt{\mathrm{Hz}}$]')
        ax.tick_params(which="both", direction="in", right=True, top=True, zorder=300)
        plt.grid(True, alpha=.5, linestyle='--')
        ax.set_xlabel(r'Frequency [Hz]')
        ax.set_yscale('log')
        ax.set_xscale('log')
        #plt.loglog(f, np.abs(1e-16/(1+1j*2*np.pi*f*20e-6)), linestyle ='-', lw=1.5, 
        #           color = 'xkcd:periwinkle', zorder=5000000) #pulse shape
        if xlims is not None:
            ax.set_xlim(xlims)
        if ylims is not None:
            ax.set_ylim(ylims)
        plt.legend(facecolor='white', framealpha=1)
        ax.set_title('Power Referenced Noise')
        fig.tight_layout()
        
    def plot_responsivity(self, figsize=(6.75, 4.455), xlims=None, ylims=None):
        noise = self.noise
        f = self.freqs
        fig, ax = plt.subplots(figsize=figsize)
        ax.loglog(f, np.abs(noise.dIdP())/np.abs(noise.dIdP())[0], color='k')
        ax.set_xlabel(r'Frequency [Hz]')
        ax.tick_params(which="both", direction="in", right=True, top=True, zorder=300)
        plt.grid(True, alpha=.5, linestyle='--')
        plt.title('Responsivity')
        ax.set_ylabel(r'$\left|\frac{\partial I}{\partial P}\left(\omega\right)\right|/\left|\frac{\partial I}{\partial P}\left(0\right)\right|$')
        
        
        
    def print(self):    
        print("---------------- DETECTOR PARAMETERS ----------------")
        print("nP =  %s" % self._n_channel)
        print("SAactive =  %s" % self._SA_active)
        print("fSA_active =  %s" % self.fSA_active)
        print("lcell =  %s" % self._l_cell)
        print("SApassive =  %s" % self._SA_passive)
        print(f'fraction total Al cov =  {self._fSA_qpabsorb}')
        print("fSA_passive =  %s" % self.fSA_passive)
        print("Alignment_area =  %s" % self.total_alignment)
        print("fSA_QPabsb =  %s" % self._fSA_qpabsorb)
        print("ePcollect =  %s" % self._ePcollect)
        print("tau_pabsb =  %s" % self._t_pabsb)
        print("w_pabsb =  %s" % (1/self._t_pabsb))
        print("eE156 =  %s" % self._e156)
        print("QP_eff =  %s" % self.QET.eQPabsb)
        print("eEabsb =  %s" % self._eEabsb)
        print("Kpb =  %s" % self._kpb)
        print("nKpb =  %s" % self._nkpb)
        print("NQET.TES =  %s" % self.QET.TES.nTES)
        print("total_L =  %s" % self.QET.TES.L)
        print("------------------------------------------------\n")
        


    

