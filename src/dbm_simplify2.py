#!/local/python3/bin/python3
'''
Simplify a curve in an additive fashion.
Start with the endpoints and add back the point
with the greatest error.  Don't worry about
integrated error, just keep it simple.
'''

import sys

lines = [x for x in [line.strip() for line in open(sys.argv[1])] if x and not x.startswith('#')]
n = int(sys.argv[2])

rows = [(float(fields[0]), float(fields[1])) for fields in [line.split() for line in lines]]
rows.sort()

# average duplicate rows together.  no cliffs allowed here.
arows = []
i = 0
while i < len(rows):
    j = i+1
    while j < len(rows) and rows[j][0] == rows[i][0]:
        j += 1
    a = sum(r[1] for r in rows[i:j]) / (j-i)
    arows.append((rows[i][0], a))
    i += 1

#x = [float(line.split()[0]) for line in lines]
#y = [float(line.split()[1]) for line in lines]
x = [r[0] for r in arows]
y = [r[1] for r in arows]

#print(x)
#print(y)

nx = [x[0], x[-1]]
ny = [y[0], y[-1]]

while len(nx) < n and len(nx) < len(x):
    # find point with max error
    ni = 0
    maxe = -1.0
    ei = 0
    nei = 1
    i = 1
    while i < len(x)-1:
        if x[i] >= nx[ni+1]:
            ni += 1
            i += 1
            continue
        f = (x[i] - nx[ni]) / (nx[ni+1] - nx[ni])
        v = ny[ni] + f*(ny[ni+1] - ny[ni])
        e = abs(v - y[i])
        if e > maxe:
            maxe = e
            ei = i
            nei = ni+1
        i += 1
    # insert max error point
    nx.insert(nei, x[ei])
    ny.insert(nei, y[ei])

# output to stdout
print('#lo_ghz dbm')
for i in range(len(nx)):
    print('%.3f %.2f'%(nx[i],ny[i]))



