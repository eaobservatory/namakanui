#!/local/python3/bin/python3
'''
Compute automatic bias voltages for namakanui b6 and b7,
trying to stay centered in the last photon step
while avoiding shapiro regions and photon step overlaps.

https://www.eso.org/sci/libraries/SPIE2012/8452-109.pdf
http://web.eecs.umich.edu/~jeast/salez_1994_1_7.pdf

Usage:
  shapiro.py <band> [mixer_ascii_file]
'''

from pylab import *
import sys
import bisect

band = int(sys.argv[1])
if band == 7:
    n = 1  # single junction
    vgap = 2.8  # nominal
    #vgap = 2.7  # this would be a better fit with band 6
    margin = .2  # from "ALMA SIS mixer optimization for stable operation" paper
    xr = [280,370]
    #xr = [600,700]  # SMA paper
elif band == 6:
    n = 4  # quadruple junction (assumed)
    vgap = 10.8  # estimated from U'u IV curves
    #margin = .2*n  # nominal
    #margin = .5  # estimated from squeeze near 237 GHz
    margin = .6  # plus a little extra
    xr = [220,270]
else:
    sys.stderr.write('band must be 6 or 7\n')
    sys.exit(1)

# planck's constant as eV*s*1e12, to produce mV when multiplied by GHz
h = 4.135667696e-3

# last step starts one photon step below vgap (TODO VERIFY VIA IV CURVE)
yr = [vgap - xr[1]*h*n - 0.1, vgap + 0.1]

# plot!
x = linspace(xr[0], xr[1], 100)
plot(x, x*0 + vgap, 'r', linewidth=2, label=None)
plot(x, vgap - x*h*n, 'r', linewidth=2, label=None)
#plot(x, vgap - x*h*n*.5, '--r', linewidth=1.5, label=None)
# negative photon step overlaps
for i in range(10):
    plot(x, x*h*n*i - vgap, 'b', label='overlap%d'%(i))
# shapiro regions
for i in range(10):
    plot(x, x*h*n*i*.5, 'm', label='shapiro%d'%(i))

def avoid(ghz, mv, margin):
    '''
    get bracketing steps.  return offset mv and distance to closer boundary.
    '''
    lo = vgap - ghz*h*n
    hi = vgap
    steps = [lo, hi]
    for i in range(10):
        photon = ghz*h*n*i - vgap
        shapiro = ghz*h*n*i*.5
        if lo < photon < hi:
            steps.append(photon)
        if lo < shapiro < hi:
            steps.append(shapiro)
    steps.sort()
    index = bisect.bisect(steps, mv)  # index of higher step
    if index == 0 or index == len(steps):
        return mv, 0.0  # out of bounds
    lo = steps[index-1]
    hi = steps[index]
    lo_m = lo + margin
    hi_m = hi - margin
    if mv >= lo_m and mv <= hi_m:
        return mv, min(mv-lo, hi-mv)  # in the clear
    if lo_m > hi_m:
        midpt = (lo+hi)*.5
        return midpt, midpt-lo  # crowded
    if (mv-lo) < (hi-mv):
        return lo_m, margin
    return hi_m, margin


# now plot the 'best' mixer bias voltages
#y = vgap - x*h*n*.5  # centered on last step
y = vgap - x*h*n*.5 + .25*margin  # centered, if lower bound moves up by .5*margin
#y = x*0.0 + vgap - .45*n  # constant offset from vgap
yprime = y.copy()
for i,ghz in enumerate(x):
    mv = y[i]
    mmv, dist = avoid(ghz, mv, margin)
    if dist < margin:  # crowded, look for a better spot in neighboring region
        eps = 1e-6
        mvlo, dlo = avoid(ghz, mmv-dist-eps, margin)
        mvhi, dhi = avoid(ghz, mmv+dist+eps, margin)
        #print('%.2f ghz: testing %.2f (%.2f), %.2f (%.2f), %.2f (%.2f)'%(ghz, mmv,dist, mvlo,dlo, mvhi, dhi))
        if dlo > (dist+eps) and dlo > (dhi+eps):
            mmv, dist = mvlo, dlo
        elif dhi > (dist+eps) and dhi > (dlo+eps):
            mmv, dist = mvhi, dhi
        elif dlo > (dist+eps) and abs(dlo-dhi)<eps:
            if (mv-mvlo+eps) < (mvhi-mv):  # bias toward higher region
                mmv, dist = mvlo, dlo
            else:
                mmv, dist = mvhi, dhi
    yprime[i] = mmv

plot(x, y, '--r', linewidth=1.5, label=None)
plot(x, yprime, 'k', label='bias')

# TODO: could just use the ini utils here

def plot_MixerParam(mparms):
    mlines = mparms.strip().split('\n')
    ghz = []
    m01 = []
    m02 = []
    m11 = []
    m12 = []
    for line in mlines:
        line = line.strip().replace(',', ' ')
        if not line or line.startswith('#') or line.startswith(';'):
            continue
        if '=' in line:
            line = line.partition('=')[-1]
        #print(line)
        fields = [abs(float(x)) for x in line.split()]
        ghz.append(fields[0])
        m01.append(fields[1])
        m02.append(fields[2])
        m11.append(fields[3])
        m12.append(fields[4])
    #print(m01)
    #print(m02)
    #print(m11)
    #print(m12)
    plot(ghz, m01, ':', color='gray', label='m01')
    plot(ghz, m02, ':', color='gray', label='m02')
    plot(ghz, m11, ':', color='gray', label='m11')
    plot(ghz, m12, ':', color='gray', label='m12')

title_str = 'Shapiro Band %d'%(band)

if len(sys.argv) > 2:
    plot_MixerParam(open(sys.argv[2].read()))
    fname = sys.argv[2]
    if '/' in fname:
        fname = fname.rpartition['/'][-1]
    title_str += ', ' + fname

title(title_str)

grid()
#legend(loc='best')
xlim(xr)
ylim(yr)
show()

