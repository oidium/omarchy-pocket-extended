import unittest
from notification_text import plain_conversation_text as plain


class NotificationTextTests(unittest.TestCase):
    def test_conversations(self):
        self.assertEqual(plain('Project update<br/><b>Casey Example</b><br/>See you soon', True), 'Project update\nCasey Example\nSee you soon')
        self.assertEqual(plain('Hi 👋 世界<br/><b>A &amp; B</b><br/>yes', True), 'Hi 👋 世界\nA & B\nyes')

    def test_literal_markup_decoded_once(self):
        self.assertEqual(plain('&lt;b&gt;literal&lt;/b&gt; &amp;lt;br/&amp;gt;', True), '<b>literal</b> &lt;br/&gt;')
        self.assertEqual(plain('&lt;img src="https://invalid"&gt;', True), '<img src="https://invalid">')

    def test_malformed_and_nonconversation(self):
        self.assertEqual(plain('a<br/><b>unfinished <b', True), 'a\nunfinished <b')
        text='a<br/><b>literal</b> &amp;'
        self.assertEqual(plain(text, False), text)
