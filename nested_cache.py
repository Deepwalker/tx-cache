#!/usr/bin/env python                                                                              
# coding: utf-8                                                                                    
"""
Nested sets varinat of memcache.
"""

from mck import *

class Entry(object):
    def __init__(self, data, flags, exptime):
        """
        Инициализация, пока нужны data, flags, exptime
        Если exptime == 0, то хранение бессрочное
        Если exptime < 60*60*24*30, то это время от текущего
        Иначе время эпохи UNIX
        """
        self.data = data
        self.flags = flags
        
        expire = int(exptime)

        if expire == 0:
            self.exptime=0
        # Если меньше чем 60*60*24*30, то есть шаг от текущего времени
        elif expire < 2592000:
            self.exptime = time.time() + expire
        # Иначе это было время эпохи UNIX 
        else:
            self.exptime = expire

        self.childs={}

    def expire(self):
        """
        Проверяем на просроченность данных
        """
        if self.exptime == 0 or self.exptime > time.time():
            return False
        else:
            return True

    def append(self, data):
        self.data = self.data + data

    def prepend(self, data):
        self.data = data + self.data

    def change(self, data):
        self.data = int(self.data)+data

    # Рекурсия
    def get_child(self, keys):
        if not keys: 
            return self
        child = self.childs.get(keys[0],None)
        # Кеш просрочен
        if child and child.expire():
            self.delete_child(keys[0])
            return None
        # Если еще не дошли до требуемого, то рекурсия
        if child and len(keys)>1:
            return child.get_child(keys[1:])
        else:
            # Дошли до нужного
            return child

    def set_child(self,key,entry):
        entry.parent = self
        self.childs[key] = entry

    def delete_child(self,key):
        if key in self.childs:
            del self.childs[key]

class Cache(BaseCache):
    # consts
    storage_commands = ["set", "add", "replace", "append", "prepend","cas"]
    oneline_commands = ["get", "gets","getn","getch","delete", "incr", "decr", "stats"]

    # cache storage
    def __init__(self):
        self.data = Entry(0,0,0)

    # cache operations
    def set(self, i):
        "set, поддержка вложенных ключей"
        parent = self.data.get_child(i.keys[:-1])
        if parent:
            parent.set_child(i.keys[-1], Entry(i.data,i.flags,i.exptime))
            yield "STORED"
        else:
            yield "NOT_STORED"

    def get(self, i):
        "get, не обрабатывает вложенные ключи"
        for key in i.keys:
            entry = self.data.get_child([key])
            if entry:
                yield ' '.join(( "VALUE", key, entry.flags, str(len(entry.data)) ))
                yield entry.data
        yield "END"

    def getn(self, i):
        "get для вложенных ключей, только один за раз"
        entry = self.data.get_child(i.keys)
        if entry:
            yield ' '.join(( "VALUE", " ".join(i.keys), entry.flags, str(len(entry.data)) ))
            yield entry.data
        yield "END"

    def getch(self, i):
        "get для вложенных ключей, только один за раз"
        entry = self.data.get_child(i.keys)
        if entry:
            data = json.dumps(entry.childs.keys())
            yield ' '.join(( "VALUE", " ".join(i.keys), entry.flags, str(len(data)) ))
            yield data
        yield "END"

    def add(self, i):
        if self.data.get_child(i.keys):
            yield "NOT_STORED"
        else:
            for res in self.set(i): yield res

    def replace(self, i):
        entry = self.data.get_child(i.keys)
        if entry:
            for res in self.set(i): yield res
        else:
            yield "NOT_STORED"

    def append(self, i):
        entry=self.data.get_child(i.keys)
        if entry:
            entry.append(i.data)
            yield "STORED"
        else:
            yield "NOT_STORED"

    def prepend(self, i):
        entry = self.data.get_child(i.keys)
        if entry:
            entry.prepend(i.data)
            yield "STORED"
        else:
            yield "NOT_STORED"

    def change_by(self, i):
        entry = self.data.get_child(i.keys)
        if entry:
            entry.change(i.change_value)
            yield str(entry.data)
        else:
            yield "NOT_FOUND"
    incr = change_by
    decr = change_by

    def cas(self, i):
        # TODO сделать, сейчас лениво
        yield "NOT_FOUND"

    def delete(self, i):
        parent = self.data.get_child(i.keys[:-1])
        if parent:
            parent.delete_child(i.keys[-1])
            yield "DELETED"
        else:
            yield "NOT_FOUND"

# Ну тут даже и писать то нечего - создает экземпляр 
# протокола на подключение клиента, по просьбе реактора
class MemcacheFactory(protocol.Factory):
    protocol = MemcacheProtocol
    cache = Cache()

# Запуск при помощи twistd -y %s
application = service.Application("memcache-key")
# Если есть желание поменять порт, то здесь
mc_service = internet.TCPServer(11211,factory=MemcacheFactory())
mc_service.setServiceParent(application)

