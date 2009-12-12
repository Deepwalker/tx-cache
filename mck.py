#!/usr/bin/env python                                                                              
# coding: utf-8                                                                                    

import time

from twisted.internet import reactor, protocol
from twisted.protocols.basic import LineOnlyReceiver
from twisted.application import internet, service   
from twisted.python import log

def debug(msg):
    log.msg(msg)

class Instruction(object):
    def __init__(self, i):
        p = i['parameters']
        self.cmd = p.pop(0)

        # Проверяем noreply
        if p[-1]=='noreply':
            self.reply=False
            # Выкидываем его
            p.pop(-1)
        else:
            self.reply=True

        if self.cmd in Cache.storage_commands:
            # Если CAS то есть еще один параметр (т.е. особый случай)
            if self.cmd == "cas":
                self.unique = p.pop(-1)

            # Теперь все параметры однозначны, но мы хотим расширить протокол,
            # потому все не так просто, как dict(zip())
            self.bytes = p.pop(-1)
            self.exptime = p.pop(-1)
            self.flags = p.pop(-1)
            self.keys=p
            self.data = i.get('data',None)

        # get и gets
        elif self.cmd in ["get","gets","getn"]:
            self.keys = p

    def __str__(self):
        return str(self.__dict__)

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
        if self.exptime == 0:
            return False
        elif time.time() > self.exptime:
            return True
        else:
            return False

    def append(self, data):
        self.data = self.data + data

    def prepend(self, data):
        self.data = data + self.data

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
        del self.childs[key]

class Cache(object):
    # consts
    storage_commands = ["set", "add", "replace", "append", "prepend","cas"]
    oneline_commands = ["get", "gets","getn", "delete", "incr", "decr", "stats"]

    # cache storage
    data = Entry(0,0,0)

    # cache operations
    @classmethod
    def call(cls, instruction):
        i = Instruction(instruction)
        debug(i)
        command = getattr(cls,i.cmd)
        return command(i)

    @classmethod
    def set(cls, i):
        "set, поддержка вложенных ключей"
        parent = cls.data.get_child(i.keys[:-1])
        if parent:
            parent.set_child(i.keys[-1], Entry(i.data,i.flags,i.exptime))
            yield "STORED"
        else:
            yield "NOT_STORED"

    @classmethod
    def get(cls, i):
        "get, не обрабатывает вложенные ключи"
        for key in i.keys:
            entry = cls.data.get_child([key])
            if entry:
                yield ' '.join(( "VALUE", key, entry.flags, str(len(entry.data)) ))
                yield entry.data
        yield "END"

    @classmethod
    def getn(cls, i):
        "get для вложенных ключей, только один за раз"
        entry = cls.data.get_child(i.keys)
        if entry:
            yield ' '.join(( "VALUE", " ".join(i.keys), entry.flags, str(len(entry.data)) ))
            yield entry.data
        yield "END"

    @classmethod
    def add(cls, i):
        if cls.data.get_child(i.keys):
            yield "NOT_STORED"
        else:
            for res in cls.set(i): yield res

    @classmethod
    def replace(cls, i):
        entry = cls.data.get_child(i.keys)
        if entry:
            for res in cls.set(i): yield res
        else:
            yield "NOT_STORED"

    @classmethod
    def append(cls, i):
        entry=cls.data.get_child(i.keys)
        if entry:
            i['data'] = entry.data + i['data']
            for res in cls.set(i): yield res
        else:
            yield "NOT_STORED"

    @classmethod
    def prepend(cls, i):
        entry = cls.data.get_child(i.keys)
        if entry:
            i['data'] = i['data'] + entry.data 
            for res in cls.set(i): yield res
        else:
            yield "NOT_STORED"

    @classmethod
    def cas(cls, i):
        # TODO сделать, сейчас лениво
        yield "NOT_FOUND"

    @classmethod
    def delete(cls, i):
        entry = cls.data.get_child(i.keys)
        if entry:
            entry.parent.delete_child(i.key)
            yield "DELETED"
        else:
            yield "NOT_FOUND"

class MemcacheProtocol(LineOnlyReceiver):
    """
    Реализует базис протокола - прием сообщений от клиента
    и отдачу результата.
    """

    def lineReceived(self,line):            
        debug(repr(line))
        if not 'parameters' in self.instruction:
            parameters = line.split(' ')
            debug("Got new command "+parameters[0])
            self.instruction['parameters']=parameters

            # Если данных не ожидается, то к исполнению
            if parameters[0] in Cache.oneline_commands:
                self.process()
        else:
            # Получены данные к двухстрочной команде, к исполнению
            debug("Got data "+line)
            self.instruction['data']=line
            self.process()

    def process(self):
        # Cache.call возвращает генератор
        for line in Cache.call(self.instruction):
            # И мы отсылаем все что он нагенерирует отдельными строками
            debug("Send line "+line)
            self.sendLine(line)
        # Готовы к дальнейшим инструкциям, насяльника!
        self.instruction={}

    def connectionMade(self):
        debug("Connected!")
        self.instruction={}

# Ну тут даже и писать то нечего - создает экземпляр 
# протокола на подключение клиента, по просьбе реактора
class MemcacheFactory(protocol.Factory):
    protocol = MemcacheProtocol

# Запуск при помощи twistd -y %s
application = service.Application("memcache-key")
# Если есть желание поменять порт, то здесь
mc_service = internet.TCPServer(11211,factory=MemcacheFactory())
mc_service.setServiceParent(application)
