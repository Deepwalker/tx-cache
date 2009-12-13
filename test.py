import memcache
import time

t=time.time()

c=memcache.Client("127.0.0.1")

print c.set("test","12")
print c.incr("test",20)

print "Set"
for i in xrange(10):
    for j in xrange(1000):
        key = str(j)+"@"+str(j)
        c.set(key,"kuku")
    print i

print time.time()-t
t=time.time()

print "Get"
for i in xrange(10):
    for j in xrange(1000):
        key = str(j)+"@"+str(j)
        c.get(key)
    print i

print time.time()-t
