import unittest

from quote_parser import parse_quotes


class UsualFormatTests(unittest.TestCase):
    def test_usual_format_reads_the_same_as_before(self):
        self.assertEqual(parse_quotes('"the robot is on fire" - Sam'), [('the robot is on fire', 'Sam', None)])
        self.assertEqual(parse_quotes('"one" - Sam "two" - <@5>'), [('one', 'Sam', None), ('two', None, 5)])


class MissingQuoteMarksTests(unittest.TestCase):
    def check(self, message, expected):
        with self.subTest(message=message):
            self.assertEqual(parse_quotes(message), [expected])

    def test_no_quote_marks(self):
        self.check('the robot is on fire - Sam', ('the robot is on fire', 'Sam', None))
        self.check('the robot is on fire -Sam Lee', ('the robot is on fire', 'Sam Lee', None))
        self.check('the robot is on fire — Sam', ('the robot is on fire', 'Sam', None))
        self.check('the robot is on fire - <@123>', ('the robot is on fire', None, 123))
        self.check('the robot is on fire <@123>', ('the robot is on fire', None, 123))

    def test_one_mark_missing(self):
        self.check('"the robot is on fire - Sam', ('the robot is on fire', 'Sam', None))
        self.check('the robot is on fire" - Sam', ('the robot is on fire', 'Sam', None))

    def test_name_right_after_the_quote(self):
        self.check('"the robot is on fire" Sam', ('the robot is on fire', 'Sam', None))

    def test_person_first(self):
        self.check('<@123> the robot is on fire', ('the robot is on fire', None, 123))
        self.check('<@!123>: "the robot is on fire"', ('the robot is on fire', None, 123))
        self.check('<@123> - the robot is on fire', ('the robot is on fire', None, 123))
        self.check('@Sam the robot is on fire', ('the robot is on fire', 'Sam', None))
        self.check('@Sam: the robot is on fire', ('the robot is on fire', 'Sam', None))

    def test_one_quote_per_line(self):
        self.assertEqual(parse_quotes('it works - Sam\n<@5> no it does not'),
                         [('it works', 'Sam', None), ('no it does not', None, 5)])


class OrdinaryChatTests(unittest.TestCase):
    def test_chat_is_not_a_quote(self):
        for message in ('who has the drill', 'see you at 5 - bring the drill', 'i love the T-Rex',
                        'a well-known Thing', 'ok we leave at 3 - Coach said so', '<@123>', '<@123> <@456>',
                        '!quote <@123>', '"the robot is on fire"', '- Sam', 'email me@example.com later'):
            with self.subTest(message=message):
                self.assertEqual(parse_quotes(message), [])


if __name__ == '__main__':
    unittest.main()
