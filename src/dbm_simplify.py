#!/local/python3/bin/python3
'''
dbm_simplify.py
RMB 20190822

I'm probably reinventing the wheel here.
This script takes a topcat-ascii file produced by dbm_table.py
and reduces it to the given number of points, by repeatedly deleting
the next point that results in the smallest interpolated error.

At any given step, there are likely to be several points that are
equally good candidates.  In this case we pick the point randomly.

Output is sent to stdout.

TODO: The results might be different if we use successive refinement instead:
      start with only the endpoints and then start adding points that
      minimize total error.

NOTE: numpy.trapz doesn't integrate errors correctly, since it is designed
      to produce a signed value, not absolute area between curve and zero.

NOTE: integrated error produces better-looking curves, but it might not
      actually be what we want.  there is a potential for causing damage
      if the power input is too high, so it's more important to limit
      maximum error than to get a lower error for more points.  And we
      might want to weight positive error less than negative error
      so we tend to stay under the curve instead of above it.
      
      What I could do is create two separate curves for -2V and -1V,
      then generate a curve that stays between them.
'''

import sys
import random
import bisect

random.seed()  # from current time or system entropy source

f = sys.stdin
if not sys.argv[1].startswith('-'):
    f = open(sys.argv[1])

target = int(sys.argv[2])
if target < 2:
    sys.stderr.write('cannot have fewer than 2 output points.')
    sys.exit(1)

def lo_ghz_key(i):
    '''only (stable) sort by lo_ghz to preserve vertical lines'''
    return i[0]

orig_table = []
for line in f:
    line = line.strip()
    if not line or line.startswith('#'):
        continue
    lo_ghz, dbm, if_total_power = [float(x) for x in line.split()]
    orig_table.append([lo_ghz, dbm])

orig_table.sort(key=lo_ghz_key)

new_table = orig_table.copy()
for i,row in enumerate(new_table):
    row.append(i)  # keep track of original row index

def trapezoid(x0,y0, x1,y1):
    '''trapezoidal area accounting for sign change.'''
    # weight pos/neg errors differently to avoid overpowering the mixer.
    # basically, try to stay under the raw curve.
    pos_weight = 2.0
    neg_weight = 0.5
    dx = abs(x1-x0)
    if y0 >= 0.0 and y1 >= 0.0:
        return (y0+y1)*0.5*dx*pos_weight
    if y0 <= 0.0 and y1 <= 0.0:
        return (y0+y1)*(-0.5)*dx*neg_weight
    #if y0*y1 >= 0.0:  # same sign
    #    return abs((y0+y1)*.5 * dx)
    # by similar triangles, x-fraction is same as y-fraction.
    y0_weight = pos_weight
    y1_weight = pos_weight
    if y0 < 0.0:
        y0_weight = neg_weight
        y0 = -y0
    if y1 < 0.0:
        y1_weight = neg_weight
        y1 = -y1
    f = y0 / (y0+y1)
    x0 = f*dx
    x1 = (1.0-f)*dx
    return y0*x0*.5*y0_weight + y1*x1*.5*y1_weight
    

# TODO this is terrible N^2 garbage.
# when we delete a point, we only need to update the errors for its neighbors.
while len(new_table) > target:
    sys.stderr.write('%d\n' % (len(new_table)))
    candidates = []
    min_error = 1e300
    epsilon = 1e-3
    for i in range(1, len(new_table)-1):  # easiest to never delete end points
        j = i-1
        k = i+1
        dlo = new_table[k][0] - new_table[j][0]
        if dlo == 0.0:
            max_error = 0.0
        else:
            # integrate the error in a segment instead of just taking the max.
            # max alone leads to to some strange-looking decisions.
            # to do this properly, we need to account for sign of error.
            oj = new_table[j][-1]
            ok = new_table[k][-1]
            max_error = -1.0
            err = 0.0
            total_err = 0.0
            for m in range(oj+1, ok):
                # interpolate new value at this original index
                f = (orig_table[m][0] - new_table[j][0]) / (dlo)
                v = new_table[j][1] + f*(new_table[k][1] - new_table[j][1])
                # check error vs original value
                #err = abs(v - orig_table[m][1]))
                #if err > max_error:
                    #max_error = err
                last_err = err
                err = v - orig_table[m][1]
                total_err += trapezoid(orig_table[m-1][0], last_err, orig_table[m][0], err)
            total_err += trapezoid(orig_table[ok-1][0], err, orig_table[ok][0], 0.0)
            max_error = total_err
                
        # new best candidate?
        if max_error < (min_error - epsilon):
            sys.stderr.write('%d: %g\n' % (i, max_error))
            min_error = max_error
            candidates = [i]
        elif abs(max_error - min_error) <= epsilon:
            candidates.append(i)
    # pick a random candidate
    i = random.choice(candidates)
    del new_table[i]

sys.stdout.write('#lo_ghz dbm\n')
for row in new_table:
    sys.stdout.write('%.3f %6.2f\n' % (row[0], row[1]))




