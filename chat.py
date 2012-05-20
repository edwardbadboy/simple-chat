__metaclass__ = type

import time
import string
from asyncore import dispatcher
from asynchat import async_chat
import socket
import asyncore

_PORT = 5005
_NAME = 'EdChat'


def now_str():
    '''Get the string representation of the current time.'''
    return time.ctime(time.time())


class _ChatSession(async_chat):
    '''Collect user data and call ChatLogics to deal with the data.'''

    def __init__(self, chatserver, sock):
        async_chat.__init__(self, sock)
        self.set_terminator('\r\n')

        self.__clientdata = []
        self.__logic = None
        self.__server = chatserver

        self.username = "anonymous"

    def collect_incoming_data(self, data):
        self.__clientdata.append(data)

    def found_terminator(self):
        line = ''.join(self.__clientdata)
        self.__clientdata = []
        self.__logic.handle_client_data(self, line)

    def handle_close(self):
        async_chat.handle_close(self)
        self.change_logic(None)

    def change_logic(self, chatlogic):
        if self.__logic is not None:
            self.__logic.handle_client_leave(self)
        self.__logic = chatlogic
        if self.__logic is not None:
            self.__logic.handle_client_enter(self)
        else:
            self.__server.user_quit(self)


class ChatLogic:
    '''A abstract class for chat logic operations.'''

    def __init__(self, chatserver):
        self._server = chatserver

    def handle_client_data(self, chatsession, data):
        '''Override this method to deal with the collected client data.'''
        pass

    def handle_client_enter(self, chatsession):
        '''Override this method to do deal with
        the event of user entering the logic.
        '''
        pass

    def handle_client_leave(self, chatsession):
        '''Override this method to do deal with
        the event of user leaving the logic.
        '''
        pass


class UnknownActionError(Exception):
    pass


class ChatRoomLogic(ChatLogic):
    '''Implement a ChatLogic to handle chat room behaviors.'''

    def __init__(self, chatserver, room_name):
        super(ChatRoomLogic, self).__init__(chatserver)
        self.__name = room_name
        self.__sessions = []

    def __broadcast_user_state(self, chatsession, state):
        self.__broadcast('%s: "%s" %s.' %
                       (now_str(), chatsession.username, state))

    def __broadcast(self, words):
        for session in self.__sessions:
            session.push(words + '\n')

    def handle_client_data(self, chatsession, data):
        if data == '':
            return
        if data[0] == '/':
            args = string.split(data[1:], ' ', 5)
            try:
                self.__dispatch_client_action(chatsession, args[0], args[1:])
            except UnknownActionError:
                chatsession.push('Unknown action: %s\n' % args[0])
            return

        self.__broadcast('%s: "%s" says:\n%s\n' %
                       (now_str(), chatsession.username, data))

    def handle_client_enter(self, chatsession):
        super(ChatRoomLogic, self).handle_client_enter(chatsession)
        self.__sessions.append(chatsession)
        chatsession.push('Welcome to %s\n' % self.__name)
        self.__broadcast_user_state(chatsession, "enters room")

    def handle_client_leave(self, chatsession):
        super(ChatRoomLogic, self).handle_client_leave(chatsession)
        self.__sessions.remove(chatsession)
        self.__broadcast_user_state(chatsession, "leaves room")

    def __dispatch_client_action(self, chatsession, action, args):
        method = getattr(self, '_do_' + action, None)
        if method is None:
            raise UnknownActionError()
        method(chatsession, args)

    def _do_quit(self, chatsession, args):
        chatsession.push('Bye!\n')
        chatsession.handle_close()
        return

    def _do_who(self, chatsession, args):
        for session in self.__sessions:
            chatsession.push(session.username + '\n')
        return


class UserNameLogic(ChatLogic):
    '''Implement a ChatLogic to handle user name selection behaviors.'''

    def __init__(self, chatserver, room_name, next_room):
        super(UserNameLogic, self).__init__(chatserver)
        self.__name = room_name
        self.__nextroom = next_room
        self.__clientnames = {}

    def __add_clientname(self, name):
        if name in self.__clientnames:
            return False
        self.__clientnames[name] = 1
        return True

    def __del_clientname(self, name):
        if name in self.__clientnames:
            del self.__clientnames[name]

    def user_quit(self, chatsession):
        self.__del_clientname(chatsession.username)

    def handle_client_data(self, chatsession, data):
        if data == "":
            chatsession.push('Please input your user name >')
            return
        if not self.__add_clientname(data):
            chatsession.push('Name exists. Please input your user name>')
            return
        chatsession.username = data
        chatsession.change_logic(self.__nextroom)

    def handle_client_enter(self, chatsession):
        super(UserNameLogic, self).handle_client_enter(chatsession)
        chatsession.push(
                'Welcome to %s\nPlease input your user name >' % self.__name)


class ChatServer(dispatcher):
    def __init__(self, port, name):
        dispatcher.__init__(self)
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.set_reuse_addr()
        self.bind(('', port))
        self.listen(5)

        self.__name = name
        self.__logics = {}
        self.__chatlogic_init()
        self.__allsessions = []

    def __chatlogic_init(self):
        mainroom = ChatRoomLogic(self, self.__name + ' Hall')
        name_mgr = UserNameLogic(self, self.__name, mainroom)
        self.__logics = {'mainroom': mainroom, 'name_mgr': name_mgr}

    def handle_accept(self):
        conn, addr = self.accept()
        # name manager is referenced by the server
        # when change_logic to a name manager or other logic
        # the chatsession will be or will not be referenced by that logic
        # so the server must own the session to keep a reference
        chatsession = _ChatSession(self, conn)
        self.__allsessions.append(chatsession)
        chatsession.change_logic(self.__logics['name_mgr'])

    def user_quit(self, chatsession):
        self.__logics['name_mgr'].user_quit(chatsession)
        try:
            self.__allsessions.remove(chatsession)
        except ValueError:
            pass


if __name__ == '__main__':
    s = ChatServer(_PORT, _NAME)
    print 'Start ChatServer at port %d' % _PORT
    try:
        asyncore.loop()
    except KeyboardInterrupt:
        print
