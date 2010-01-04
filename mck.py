#!/usr/bin/env python                                                                              
# coding: utf-8                                                                                    
"""
MemCacheKey - фреймворк для создания memcache-велосипедов любых форм и расцветок.
"""
import time
import json

from twisted.internet import reactor, protocol
from twisted.protocols.basic import LineOnlyReceiver
from twisted.application import internet, service   
from twisted.python import log

def debug(msg):
    log.msg(msg)

class Instruction(object):
    def __init__(self, i, cache):
        p = i['parameters']
        self.cmd = p.pop(0)

        # Проверяем noreply
        if p[-1]=='noreply':
            self.reply=False
            # Выкидываем его
            p.pop(-1)
        else:
            self.reply=True

        if self.cmd in cache.storage_commands:
            # Если CAS то есть еще один параметр (т.е. особый случай)
            if self.cmd == "cas":
                self.unique = p.pop(-1)

            # Теперь все параметры однозначны, но мы хотим расширить протокол,
            # потому все не так просто, как dict(zip())
            self.bytes = p.pop(-1)
            self.exptime = p.pop(-1)
            self.flags = p.pop(-1)
            self.data = i.get('data',None)

        # incr, decr
        elif self.cmd=="incr":
            self.change_value = int(p.pop(-1))
        elif self.cmd=="decr":
            self.change_value = -int(p.pop(-1))

        self.keys = p

    def __str__(self):
        return str(self.__dict__)

class BaseCache(object):
    storage_commands = []
    oneline_commands = []

    def call(self, instruction):
        i = Instruction(instruction,self)
        debug(i)
        command = getattr(self,i.cmd)
        return command(i)

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
            if parameters[0] in self.factory.cache.oneline_commands:
                self.process()
        else:
            # Получены данные к двухстрочной команде, к исполнению
            debug("Got data "+line)
            self.instruction['data']=line
            self.process()

    def process(self):
        # Cache.call возвращает генератор
        for line in self.factory.cache.call(self.instruction):
            # И мы отсылаем все что он нагенерирует отдельными строками
            debug("Send line "+line)
            self.sendLine(line)
        # Готовы к дальнейшим инструкциям, насяльника!
        self.instruction={}

    def connectionMade(self):
        debug("Connected!")
        self.instruction={}

