import memcache
import time

t=time.time()

print "Set"
for i in xrange(10):
    c=memcache.Client("127.0.0.1")
    for j in xrange(1000):
        key = str(j)+"@"+str(j)
        c.set(key,"kuku")
    print i

print time.time()-t
t=time.time()

print "Get"
for i in xrange(10):
    c=memcache.Client("127.0.0.1")
    for j in xrange(1000):
        key = str(j)+"@"+str(j)
        c.get(key)
    print i

print time.time()-t
