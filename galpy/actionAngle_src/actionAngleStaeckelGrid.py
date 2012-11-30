###############################################################################
#   actionAngle: a Python module to calculate  actions, angles, and frequencies
#
#      class: actionAngleStaeckelGrid
#
#             build grid in integrals of motion to quickly evaluate 
#             actionAngleStaeckel
#
#      methods:
#             __call__: returns (jr,lz,jz)
#
###############################################################################
import math
import numpy
from scipy import interpolate, optimize, ndimage
import actionAngleStaeckel
from galpy.actionAngle import actionAngle, UnboundError
import galpy.potential
from galpy.util import multi, bovy_coords
from matplotlib import pyplot
_PRINTOUTSIDEGRID= False
class actionAngleStaeckelGrid():
    """Action-angle formalism for axisymmetric potentials using Binney (2012)'s Staeckel approximation, grid-based interpolation"""
    def __init__(self,pot=None,delta=None,Rmax=5.,
                 nE=25,npsi=25,nLz=25,numcores=1,
                 **kwargs):
        """
        NAME:
           __init__
        PURPOSE:
           initialize an actionAngleStaeckelGrid object
        INPUT:
           pot= potential or list of potentials
           delta= focus of prolate confocal coordinate system
           Rmax = Rmax for building grids
           nE=, npsi=, nLz= grid size
           numcores= number of cpus to use to parallellize
           +scipy.integrate.quad keywords
        OUTPUT:
        HISTORY:
            2012-11-29 - Written - Bovy (IAS)
        """
        if pot is None:
            raise IOError("Must specify pot= for actionAngleStaeckelGrid")
        self._pot= pot
        if delta is None:
            raise IOError("Must specify delta= for actionAngleStaeckelGrid")
        self._delta= delta
        self._Rmax= Rmax
        self._Rmin= 0.01
        #Set up the actionAngleStaeckel object that we will use to interpolate
        self._aA= actionAngleStaeckel.actionAngleStaeckel(pot=self._pot,delta=self._delta)
        #Build grid
        self._Lzmin= 0.01
        self._Lzs= numpy.linspace(self._Lzmin,
                                  self._Rmax\
                                      *galpy.potential.vcirc(self._pot,
                                                             self._Rmax),
                                  nLz)
        self._Lzmax= self._Lzs[-1]
        self._nLz= nLz
        #Calculate E_c(R=RL), energy of circular orbit
        self._RL= numpy.array([galpy.potential.rl(self._pot,l) for l in self._Lzs])
        self._RLInterp= interpolate.InterpolatedUnivariateSpline(self._Lzs,
                                                                 self._RL,k=3)
        self._ERL= numpy.array([galpy.potential.evaluatePotentials(self._RL[ii],0.,self._pot) +self._Lzs[ii]**2./2./self._RL[ii]**2. for ii in range(nLz)])
        self._ERLmax= numpy.amax(self._ERL)+1.
        self._ERLInterp= interpolate.InterpolatedUnivariateSpline(self._Lzs,
                                                                  numpy.log(-(self._ERL-self._ERLmax)),k=3)
        self._Ramax= 99.
        self._ERa= numpy.array([galpy.potential.evaluatePotentials(self._Ramax,0.,self._pot) +self._Lzs[ii]**2./2./self._Ramax**2. for ii in range(nLz)])
        self._ERamax= numpy.amax(self._ERa)+1.
        self._ERaInterp= interpolate.InterpolatedUnivariateSpline(self._Lzs,
                                                                  numpy.log(-(self._ERa-self._ERamax)),k=3)
        y= numpy.linspace(0.,1.,nE)
        self._nE= nE
        psis= numpy.linspace(0.,1.,npsi)*numpy.pi/2.
        self._npsi= npsi
        jr= numpy.zeros((nLz,nE,npsi))
        jz= numpy.zeros((nLz,nE,npsi))
        u0= numpy.zeros((nLz,nE))
        jrLz= numpy.zeros(nLz)
        jzLz= numpy.zeros(nLz)
        if numcores > 1:
            raise NotImplementedError("'numcores > 1' not yet supported...")
            thisRL= (numpy.tile(self._RL,(nEr-1,1)).T).flatten()
            thisLzs= (numpy.tile(self._Lzs,(nEr-1,1)).T).flatten()
            thisERRL= (numpy.tile(self._ERRL,(nEr-1,1)).T).flatten()
            thisERRa= (numpy.tile(self._ERRa,(nEr-1,1)).T).flatten()
            thisy= (numpy.tile(y[0:-1],(nLz,1))).flatten()
            mjr= multi.parallel_map((lambda x: self._aA.JR(thisRL[x],
                                                          numpy.sqrt(2.*(thisERRa[x]+thisy[x]*(thisERRL[x]-thisERRa[x])-galpy.potential.evaluatePotentials(thisRL[x],0.,self._pot))-thisLzs[x]**2./thisRL[x]**2.),
                                                          thisLzs[x]/thisRL[x],
                                                          0.,0.,
                                                          **kwargs)[0]),
                                   range((nEr-1)*nLz),
                                   numcores=numcores)
            jr[:,0:-1]= numpy.reshape(mjr,(nLz,nEr-1))
            jrERRa[0:nLz]= jr[:,0]
        else:
            for ii in range(nLz):
                print ii
                for jj in range(nE):
                    thisLz= self._Lzs[ii]
                    #thisE= self._ERa[ii]+y[jj]*(self._ERL[ii]-self._ERa[ii])
                    thisE= _invEfunc(_Efunc(self._ERa[ii])+y[jj]*(_Efunc(self._ERL[ii])-_Efunc(self._ERa[ii])))
                    u0[ii,jj]= self.calcu0(thisE,thisLz)
                    thisR= self._delta*numpy.sinh(u0[ii,jj])
                    thisv= self.vatu0(thisE,thisLz,u0[ii,jj],thisR)
                    for kk in range(npsi):
                        try:
                            thisaA= actionAngleStaeckel.actionAngleStaeckelSingle(\
                                thisR, #R
                                thisv*numpy.cos(psis[kk]), #vR
                                thisLz/thisR, #vT
                                0., #z
                                thisv*numpy.sin(psis[kk]), #vz
                                pot=self._pot,delta=self._delta)
                            jr[ii,jj,kk]= thisaA.JR(**kwargs)[0]
                            jz[ii,jj,kk]= thisaA.Jz(**kwargs)[0]
                            #print jr[ii,jj,kk]
                        except UnboundError:
                            raise
                #Normalize
                jr[numpy.isnan(jr)]= 0. #sometimes we fail ...
                jz[numpy.isnan(jz)]= 0.
                jrLz[ii]= numpy.amax(jr[ii,:,:])
                jr[ii,:,:]/= jrLz[ii]
                jzLz[ii]= numpy.amax(jz[ii,:,:])
                jz[ii,:,:]/= jzLz[ii]
        #First interpolate the maxima
        self._jr= jr
        self._jz= jz
        self._u0= u0
        self._jrLzInterp= interpolate.InterpolatedUnivariateSpline(self._Lzs,
                                                                   numpy.log(jrLz+10.**-5.),k=3)
        self._jzLzInterp= interpolate.InterpolatedUnivariateSpline(self._Lzs,
                                                                   numpy.log(jzLz+10.**-5.),k=3)
        #Interpolate u0
        self._logu0Interp= interpolate.RectBivariateSpline(self._Lzs,
                                                           y,
                                                           numpy.log(u0),
                                                           kx=3,ky=3,s=0.)
        #spline filter jr and jz, such that they can be used with ndimage.map_coordinates
        self._jrFiltered= ndimage.spline_filter(self._jr)
        self._jzFiltered= ndimage.spline_filter(self._jz)
        return None

    def __call__(self,*args,**kwargs):
        """
        NAME:
           __call__
        PURPOSE:
           evaluate the actions (jr,lz,jz)
        INPUT:
           Either:
              R,vR,vT,z,vz
           scipy.integrate.quadrature keywords (for off-the-grid calcs)
        OUTPUT:
           (jr,lz,jz)
        HISTORY:
           2012-11-29 - Written - Bovy (IAS)
        """
        if len(args) == 5: #R,vR.vT, z, vz
            R,vR,vT, z, vz= args
        elif len(args) == 6: #R,vR.vT, z, vz, phi
            R,vR,vT, z, vz, phi= args
        else:
            meta= actionAngle(*args)
            R= meta._R
            vR= meta._vR
            vT= meta._vT
            z= meta._z
            vz= meta._vz
        #Radial action
        Lz= R*vT
        Phi= galpy.potential.evaluatePotentials(R,z,self._pot)
        E= Phi+vR**2./2.+vT**2./2.+vz**2./2.
        thisRL= self._RLInterp(Lz)
        thisERL= -numpy.exp(self._ERLInterp(Lz))+self._ERLmax
        thisERa= -numpy.exp(self._ERaInterp(Lz))+self._ERamax
        if isinstance(R,numpy.ndarray):
            if len(R) == 1:
                thisERL= numpy.array([thisERL])
                thisERa= numpy.array([thisERa])
            indx= ((E-thisERa)/(thisERL-thisERa) > 1.)\
                *(((E-thisERa)/(thisERL-thisERa)-1.) < 10.**-2.)
            E[indx]= thisERL[indx]
            indx= ((E-thisERa)/(thisERL-thisERa) < 0.)\
                *((E-thisERa)/(thisERL-thisERa) > -10.**-2.)
            E[indx]= thisERa[indx]
            indx= (Lz < self._Lzmin)
            indx+= (Lz > self._Lzmax)
            indx+= ((E-thisERa)/(thisERL-thisERa) > 1.)
            indx+= ((E-thisERa)/(thisERL-thisERa) < 0.)
            indxc= True-indx
            jr= numpy.empty(R.shape)
            jz= numpy.empty(R.shape)
            u0= numpy.exp(self._logu0Interp.ev(Lz[indxc],
                                               (E[indxc]-thisERa[indxc])/(thisERL[indxc]-thisERa[indxc])))
            sinh2u0= numpy.sinh(u0)**2.
            thisEr= self.Er(R[indxc],z[indxc],vR[indxc],vz[indxc],
                            E[indxc],Lz[indxc],sinh2u0,u0)
            thisv2= self.vatu0(E[indxc],Lz[indxc],u0,self._delta*numpy.sinh(u0),retv2=True)
            cos2psi= 2.*thisEr/thisv2/(1.+sinh2u0) #latter is cosh2u0
            cos2psi[(cos2psi > 1.)*(cos2psi < 1.+10.**-5.)]= 1.
            psi= numpy.arccos(numpy.sqrt(cos2psi))
            coords= numpy.empty((3,numpy.sum(indxc)))
            coords[0,:]= (Lz[indxc]-self._Lzmin)/(self._Lzmax-self._Lzmin)*(self._nLz-1.)
            #coords[1,:]= (E[indxc]-thisERa[indxc])/(thisERL[indxc]-thisERa[indxc])*(self._nE-1.)
            coords[1,:]= (_Efunc(E[indxc])-_Efunc(thisERa[indxc]))/(_Efunc(thisERL[indxc])-_Efunc(thisERa[indxc]))*(self._nE-1.)
            coords[2,:]= psi/numpy.pi*2.*(self._npsi-1.)
            jr[indxc]= ndimage.interpolation.map_coordinates(self._jrFiltered,
                                                             coords,
                                                             order=3,
                                                             prefilter=False)*(numpy.exp(self._jrLzInterp(Lz[indxc]))-10.**-5.)
            jz[indxc]= ndimage.interpolation.map_coordinates(self._jzFiltered,
                                                             coords,
                                                             order=3,
                                                             prefilter=False)*(numpy.exp(self._jzLzInterp(Lz[indxc]))-10.**-5.)
            if numpy.sum(indx) > 0:
                raise NotImplementedError("outside the grid not yet implemented")
                jrindiv= numpy.empty(numpy.sum(indx))
                for ii in range(numpy.sum(indx)):
                    try:
                        jrindiv[ii]= self._aA.JR(thisRL[indx][ii],
                                                 numpy.sqrt(2.*(ER[indx][ii]-galpy.potential.evaluatePotentials(thisRL[indx][ii],0.,self._pot))-ERLz[indx][ii]**2./thisRL[indx][ii]**2.),
                                                 ERLz[indx][ii]/thisRL[indx][ii],
                                                 0.,0.,
                                                 **kwargs)[0]
                    except (UnboundError,OverflowError):
                        jrindiv[ii]= numpy.nan
                jr[indx]= jrindiv
        else:
            jr,Lz, jz= self(numpy.array([R]),
                            numpy.array([vR]),
                            numpy.array([vT]),
                            numpy.array([z]),
                            numpy.array([vz]),
                            **kwargs)
            return (jr[0],Lz[0],jz[0])
        return (jr,R*vT,jz)

    def Jz(self,*args,**kwargs):
        """
        NAME:
           Jz
        PURPOSE:
           evaluate the action jz
        INPUT:
           Either:
              a) R,vR,vT,z,vz
              b) Orbit instance: initial condition used if that's it, orbit(t)
                 if there is a time given as well
           scipy.integrate.quadrature keywords
        OUTPUT:
           jz
        HISTORY:
           2012-07-30 - Written - Bovy (IAS@MPIA)
        """
        raise NotImplementedError("'Jz' not yet implemented")
        meta= actionAngle(*args)
        Phi= galpy.potential.evaluatePotentials(meta._R,meta._z,self._pot)
        Phio= galpy.potential.evaluatePotentials(meta._R,0.,self._pot)
        Ez= Phi-Phio+meta._vz**2./2.
        #Bigger than Ezzmax?
        thisEzZmax= numpy.exp(self._EzZmaxsInterp(meta._R))
        if meta._R > self._Rmax or meta._R < self._Rmin or (Ez != 0. and numpy.log(Ez) > thisEzZmax): #Outside of the grid
            if _PRINTOUTSIDEGRID:
                print "Outside of grid in Ez"
            jz= self._aA.Jz(meta._R,0.,1.,#these two r dummies
                            0.,math.sqrt(2.*Ez),
                            **kwargs)[0]
        else:
            jz= (self._jzInterp(meta._R,Ez/thisEzZmax)\
                *(numpy.exp(self._jzEzmaxInterp(meta._R))-10.**-5.))[0][0]
        return jz

    def vatu0(self,E,Lz,u0,R,retv2=False):
        """
        NAME:
           vatu0
        PURPOSE:
           calculate the velocity at u0
        INPUT:
           E - energy
           Lz - angular momentum
           u0 - u0
           R - radius corresponding to u0,pi/2.
           retv2= (False), if True return v^2
        OUTPUT:
           velocity
        HISTORY:
           2012-11-29 - Written - Bovy (IAS)
        """                        
        v2= (2.*(E-actionAngleStaeckel.potentialStaeckel(u0,numpy.pi/2.,
                                                         self._pot,
                                                         self._delta))
             -Lz**2./R**2.)
        if retv2: return v2
        if isinstance(E,float) and v2 < 0. and v2 > -10.**-7.: 
            return 0. #rounding errors
        elif isinstance(E,float):
            return numpy.sqrt(v2)
        elif isinstance(v2,numpy.ndarray):
            v2[(v2 < 0.)*(v2 > -10.**-7.)]= 0.
            return numpy.sqrt(v2)
    
    def calcu0(self,E,Lz):
        """
        NAME:
           calcu0
        PURPOSE:
           calculate the minimum of the u potential
        INPUT:
           E - energy
           Lz - angular momentum
        OUTPUT:
           u0
        HISTORY:
           2012-11-29 - Written - Bovy (IAS)
        """                           
        logu0= optimize.brent(_u0Eq,
                              args=(self._delta,self._pot,
                                    E,Lz**2./2.))
        return numpy.exp(logu0)

    def Er(self,R,z,vR,vz,E,Lz,sinh2u0,u0):
        """
        NAME:
           Er
        PURPOSE:
           calculate the 'radial energy'
        INPUT:
           R, z, vR, vz - coordinates
           E - energy
           Lz - angular momentum
           sinh2u0, u0 - sinh^2 and u0
        OUTPUT:
           Er
        HISTORY:
           2012-11-29 - Written - Bovy (IAS)
        """                           
        u,v= bovy_coords.Rz_to_uv(R,z,self._delta)
        pu= (vR*numpy.cosh(u)*numpy.sin(v)
             +vz*numpy.sinh(u)*numpy.cos(v)) #no delta, bc we will divide it out
        out= (pu**2./2.+Lz**2./2./self._delta**2.*(1./numpy.sinh(u)**2.-1./sinh2u0)
              -E*(numpy.sinh(u)**2.-sinh2u0)
              +(numpy.sinh(u)**2.+1.)*actionAngleStaeckel.potentialStaeckel(u,numpy.pi/2.,self._pot,self._delta)
              -(sinh2u0+1.)*actionAngleStaeckel.potentialStaeckel(u0,numpy.pi/2.,self._pot,self._delta))
#              +(numpy.sinh(u)**2.+numpy.sin(v)**2.)*actionAngleStaeckel.potentialStaeckel(u,v,self._pot,self._delta)
#              -(sinh2u0+numpy.sin(v)**2.)*actionAngleStaeckel.potentialStaeckel(u0,v,self._pot,self._delta))
        return out


def _u0Eq(logu,delta,pot,E,Lz22):
    """The equation that needs to be minimized to find u0"""
    u= numpy.exp(logu)
    sinh2u= numpy.sinh(u)**2.
    cosh2u= numpy.cosh(u)**2.
    dU= cosh2u*actionAngleStaeckel.potentialStaeckel(u,numpy.pi/2.,pot,delta)
    return -(E*sinh2u-dU-Lz22/delta**2./sinh2u)

def _Efunc(E):
    """Function to apply to the energy in building the grid (e.g., if this is a log, then the grid will be logarithmic"""
    return numpy.exp(-E)
def _invEfunc(Ef):
    """Inverse of Efunc"""
    return -numpy.log(Ef)