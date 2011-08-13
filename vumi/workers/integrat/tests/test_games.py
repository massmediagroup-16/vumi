from twisted.trial import unittest
from twisted.internet.defer import inlineCallbacks
from twisted.internet import reactor
from twisted.web.server import Site
from twisted.web.resource import Resource
from twisted.web.static import Data

from vumi.tests.utils import get_stubbed_worker, FakeRedis
from vumi.workers.integrat.games import (RockPaperScissorsGame,
                                         RockPaperScissorsWorker,
                                         HangmanGame,
                                         HangmanWorker)

import string


class WorkerStubMixin(object):
    def _get_replies(self):
        if not hasattr(self, '_replies'):
            self._replies = []
        return self._replies

    def _set_replies(self, value):
        self._replies = value

    replies = property(fget=_get_replies, fset=_set_replies)

    def reply(self, sid, message):
        self.replies.append(('reply', sid, message))

    def end(self, sid, message):
        self.replies.append(('end', sid, message))


class TestRockPaperScissorsGame(unittest.TestCase):
    def get_game(self, scores=None):
        game = RockPaperScissorsGame(5, 'p1')
        game.set_player_2('p2')
        if scores is not None:
            game.scores = scores
        return game

    def test_game_init(self):
        game = RockPaperScissorsGame(5, 'p1')
        self.assertEquals('p1', game.player_1)
        self.assertEquals(None, game.player_2)
        self.assertEquals((0, 0), game.scores)
        self.assertEquals(None, game.current_move)

        game.set_player_2('p2')
        self.assertEquals('p1', game.player_1)
        self.assertEquals('p2', game.player_2)
        self.assertEquals((0, 0), game.scores)
        self.assertEquals(None, game.current_move)

    def test_game_moves_draw(self):
        game = self.get_game((1, 1))
        game.move('p1', 1)
        self.assertEquals(1, game.current_move)
        self.assertEquals((1, 1), game.scores)

        game.move('p2', 1)
        self.assertEquals(None, game.current_move)
        self.assertEquals((1, 1), game.scores)

    def test_game_moves_win(self):
        game = self.get_game((1, 1))
        game.move('p1', 1)
        self.assertEquals(1, game.current_move)
        self.assertEquals((1, 1), game.scores)

        game.move('p2', 2)
        self.assertEquals(None, game.current_move)
        self.assertEquals((2, 1), game.scores)

    def test_game_moves_lose(self):
        game = self.get_game((1, 1))
        game.move('p1', 1)
        self.assertEquals(1, game.current_move)
        self.assertEquals((1, 1), game.scores)

        game.move('p2', 3)
        self.assertEquals(None, game.current_move)
        self.assertEquals((1, 2), game.scores)


class RockPaperScissorsWorkerStub(WorkerStubMixin, RockPaperScissorsWorker):
    pass


class TestRockPaperScissorsWorker(unittest.TestCase):
    def get_worker(self):
        worker = get_stubbed_worker(RockPaperScissorsWorkerStub, {
                'transport_name': 'foo',
                'ussd_code': '99999',
                })
        worker.startWorker()
        return worker

    def test_new_sessions(self):
        worker = self.get_worker()
        self.assertEquals({}, worker.games)
        self.assertEquals(None, worker.open_game)

        worker.new_session({'transport_session_id': 'sp1'})
        self.assertNotEquals(None, worker.open_game)
        game = worker.open_game
        self.assertEquals({'sp1': game}, worker.games)

        worker.new_session({'transport_session_id': 'sp2'})
        self.assertEquals(None, worker.open_game)
        self.assertEquals({'sp1': game, 'sp2': game}, worker.games)

        self.assertEquals(2, len(worker.replies))

    def test_moves(self):
        worker = self.get_worker()
        worker.new_session({'transport_session_id': 'sp1'})
        game = worker.open_game
        worker.new_session({'transport_session_id': 'sp2'})
        worker.replies = []

        worker.resume_session({'transport_session_id': 'sp2', 'message': '1'})
        self.assertEquals([], worker.replies)
        worker.resume_session({'transport_session_id': 'sp1', 'message': '2'})
        self.assertEquals(2, len(worker.replies))
        self.assertEquals((0, 1), game.scores)


class TestHangmanGame(unittest.TestCase):
    def test_easy_game(self):
        game = HangmanGame(word='moo')
        game.event('m')
        game.event('o')
        self.assertTrue(game.won())
        self.assertTrue(game.state().startswith("moo:mo:Flawless"))

    def test_incorrect_guesses(self):
        game = HangmanGame(word='moo')
        game.event('f')
        game.event('g')
        self.assertFalse(game.won())
        self.assertTrue(game.state().startswith("moo:fg:Word contains no"))

    def test_repeated_guesses(self):
        game = HangmanGame(word='moo')
        game.event('f')
        game.event('f')
        self.assertFalse(game.won())
        self.assertTrue(game.state().startswith("moo:f:You've already"))

    def test_button_mashing(self):
        game = HangmanGame(word='moo')
        for event in string.lowercase.replace('o', ''):
            game.event(event)
        game.event('o')
        self.assertTrue(game.won())
        self.assertEqual(game.state(),
                         "moo:%s:Button mashing!" % string.lowercase)

    def test_new_game(self):
        game = HangmanGame(word='moo')
        for event in ('m', 'o', '-'):
            game.event(event)
        self.assertEqual(game.state(), 'moo:mo:Flawless victory!')
        self.assertEqual(game.exit_code, game.DONE_WANTS_NEW)

    def test_from_state(self):
        game = HangmanGame.from_state("bar:xyz:Eep?")
        self.assertEqual(game.word, "bar")
        self.assertEqual(game.guesses, set("xyz"))
        self.assertEqual(game.msg, "Eep?")
        self.assertEqual(game.exit_code, game.NOT_DONE)

    def test_exit(self):
        game = HangmanGame('elephant')
        game.event('0')
        self.assertEqual(game.exit_code, game.DONE)
        self.assertEqual(game.draw_board(), "Adieu!")

    def test_draw_board(self):
        game = HangmanGame('word')
        board = game.draw_board()
        msg, word, guesses, prompt, end = board.split("\n")
        self.assertEqual(msg, "New game!")
        self.assertEqual(word, "Word: ____")
        self.assertEqual(guesses, "Letters guessed so far: ")
        self.assertEqual(prompt, "Enter next guess (0 to quit):")

    def test_draw_board_at_end_of_game(self):
        game = HangmanGame('m')
        game.event('m')
        board = game.draw_board()
        msg, word, guesses, prompt, end = board.split("\n")
        self.assertEqual(msg, "Flawless victory!")
        self.assertEqual(word, "Word: m")
        self.assertEqual(guesses, "Letters guessed so far: m")
        self.assertEqual(prompt, "Enter anything to start a new game"
                                 " (0 to quit):")

    def test_displaying_word(self):
        game = HangmanGame('word')
        game.event('w')
        game.event('r')
        board = game.draw_board()
        _msg, word, _guesses, _prompt, _end = board.split("\n")
        self.assertEqual(word, "Word: w_r_")

    def test_garbage_input(self):
        game = HangmanGame(word="zoo")
        for garbage in [
            ":", "!", "\x00", "+", "abc", "",
            ]:
            game.event(garbage)
        self.assertEqual(game.guesses, set())
        game.event('z')
        game.event('o')
        self.assertTrue(game.won())


class HangmanWorkerStub(WorkerStubMixin, HangmanWorker):
    pass


class TestHangmanWorker(unittest.TestCase):
    @inlineCallbacks
    def setUp(self):
        root = Resource()
        root.putChild("word", Data('elephant', 'text/html'))
        site_factory = Site(root)
        self.webserver = yield reactor.listenTCP(0, site_factory)
        addr = self.webserver.getHost()
        random_word_url = "http://%s:%s/word" % (addr.host, addr.port)

        self.worker = get_stubbed_worker(HangmanWorkerStub, {
                'transport_name': 'foo',
                'ussd_code': '99999',
                'random_word_url': random_word_url,
                })
        yield self.worker.startWorker()
        self.worker.r_server = FakeRedis()

    @inlineCallbacks
    def tearDown(self):
        yield self.webserver.loseConnection()

    @inlineCallbacks
    def test_new_session(self):
        yield self.worker.new_session({'transport_session_id': 'sp1',
                                       'sender': '+134567'})
        self.assertEqual(len(self.worker.replies), 1)

        reply = self.worker.replies[0]
        self.assertEqual(reply[:2], ('reply', 'sp1'))
        self.assertEqual(reply[2],
                         "New game!\n"
                         "Word: ________\n"
                         "Letters guessed so far: \n"
                         "Enter next guess (0 to quit):\n")

    @inlineCallbacks
    def test_random_word(self):
        word = yield self.worker.random_word()
        self.assertEqual(word, 'elephant')

    @inlineCallbacks
    def test_full_session(self):
        session_data = {
            'transport_session_id': 'sp1',
            'sender': '+134567',
            }

        def resume(event):
            data = session_data.copy()
            data['message'] = event
            return self.worker.resume_session(data)

        yield self.worker.new_session(session_data)
        for event in ('e', 'l', 'p', 'h', 'a', 'n', 'o', 't'):
            yield resume(event)

        self.assertEqual(len(self.worker.replies), 9)

        last_reply = self.worker.replies[-1]
        self.assertEqual(last_reply[:2], ('reply', 'sp1'))
        self.assertEqual(last_reply[2],
                         "Epic victory!\n"
                         "Word: elephant\n"
                         "Letters guessed so far: aehlnopt\n"
                         "Enter anything to start a new game (0 to quit):\n")

        yield resume('1')

        last_reply = self.worker.replies[-1]
        self.assertEqual(last_reply[:2], ('reply', 'sp1'))
        self.assertEqual(last_reply[2],
                         "New game!\n"
                         "Word: ________\n"
                         "Letters guessed so far: \n"
                         "Enter next guess (0 to quit):\n")

        yield resume('0')
        last_reply = self.worker.replies[-1]
        self.assertEqual(last_reply[:2], ('end', 'sp1'))
        self.assertEqual(last_reply[2], "Adieu!")

    @inlineCallbacks
    def test_close_session(self):
        yield self.worker.close_session({'transport_session_id': 'sp1',
                                       'sender': '+134567'})
        self.assertEqual(self.worker.replies, [])
