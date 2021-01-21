#!/local/python3/bin/python3
'''
shapiro.py      RMB 20200630

Compute automatic bias voltages for namakanui b6 and b7,
trying to stay centered in the last photon step
while avoiding shapiro regions and photon step overlaps.

https://www.eso.org/sci/libraries/SPIE2012/8452-109.pdf
http://web.eecs.umich.edu/~jeast/salez_1994_1_7.pdf

Usage:
  shapiro.py <band> [mixer_ascii_file]



Copyright (C) 2020 East Asian Observatory

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
'''


import sys
import bisect
import argparse

parser = argparse.ArgumentParser(description='''
''',
  formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('band', type=int, choices=[6,7])
parser.add_argument('filename', nargs='?', default='')
parser.add_argument('--lo', nargs='?', default='')
args = parser.parse_args()

band = args.band
if band == 7:
    n = 1  # single junction
    vgap = 2.8  # nominal
    #vgap = 2.7  # this would be a better fit with band 6
    #margin = .2  # from "ALMA SIS mixer optimization for stable operation" paper
    margin = .3  # plus a little (a lot) extra
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

# calculate some shapiro steps for each freq
if args.lo:
    if ':' in args.lo:
        import namakanui.util
        los = namakanui.util.parse_range(args.lo, maxlen=100e3)
    else:
        los = [float(x) for x in args.lo.replace(',', ' ').split()]
    for lo in los:
        sys.stdout.write('%.3f:'%(lo))
        p = vgap - lo*h*n
        for i in range(10):
            s = lo*h*n*i*.5
            if s > p and s < vgap:
                sys.stdout.write(' %.3f'%(s))
        sys.stdout.write('\n')
        sys.stdout.flush()

# plot!
from pylab import *

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
    if band == 7:
        offset = 0.09
        plot(x, x*h*n*i*.5 + offset, 'm--', label='shapoff%d'%(i))

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
        if band == 7:
            photon = 0.0  # ignore negative photon steps
            shapiro += 0.09  # empirical fudge factor
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

if args.filename:
    plot_MixerParam(open(args.filename).read())
    fname = args.filename.rpartition('/')[-1]
    title_str += ', ' + fname

if band == 7:
    # empirical shapiro region centers
    x = [283, 287, 291, 295, 299, 303, 307,  331, 339,  365]
    y1 = [1.90, 1.91, 1.92, 1.94, 1.96, 1.97, 2.00, 1.41,  1.55,  1.62]
    y2 = [2.42, 2.46, 2.48, 2.51, 2.55, 2.57, 2.61, 2.13,  2.18,  2.35]
    plot(x,y1, 'go')
    plot(x,y2, 'go')

title(title_str)

grid()
#legend(loc='best')
xlim(xr)
ylim(yr)
show()

'''
empirical shapiro regions for band 7.  need to find a better relation.
plot edges and avg to find center; don't use the central spike.
      a1    a2    ac    b1   b2   bc     c1   c2   cc
283:                   1.72 2.02 1.87   2.26 2.57 2.41
                       1.78 2.06 1.92   2.30 2.58 2.44
                       
287:                   1.73 2.05 1.89   2.29 2.60 2.45
                       1.78 2.07 1.93   2.32 2.62 2.47
                       
291:                   1.74 2.06 1.90   2.33 2.61 2.47
                       1.79 2.09 1.94   2.36 2.63 2.49
                       
295:                   1.77 2.08 1.92   2.37 2.63 2.50
                       1.81 2.11 1.96   2.41 2.66 2.53
                       
299:                   1.78 2.10 1.94   2.41 2.67 2.54
                       1.83 2.13 1.98   2.44 2.68 2.56

303:                   1.80 2.13 1.96   2.44 2.69 2.56
                       1.84 2.14 1.99   2.48 2.70 2.59

307:                   1.81 2.15 1.98   2.48 2.70 2.59
                       1.87 2.17 2.02   2.52 2.74 2.63

331:                   1.31 1.51 1.41   1.93 2.30 2.12
                       1.26 1.55 1.40   1.98 2.32 2.15

339:                   1.98 2.35 2.16
                       2.02 2.37 2.20
                       
365:                   1.43 1.80 1.61   2.15 2.52 2.33
                       1.48 1.79 1.63   2.21 2.53 2.37
'''
