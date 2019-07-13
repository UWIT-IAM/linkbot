"""Flask app that listens on / and processes slack events and commands."""
import logconfig
from flask import Flask, request, jsonify, abort
import slack
import os
import time
import hmac
import hashlib
import json.decoder
import requests
from functools import partial
from threading import Thread
from queue import Queue
from linkbot import bots, RequestLogger


app = Flask(__name__)
app.config.from_pyfile(os.environ['APP_CONFIG'])
SLACK_SECRET = app.config['SLACK_SIGNING_SECRET']
SLACK_CLIENT = slack.WebClient(app.config['SLACK_BOT_TOKEN'])
WEBHOOK_CLIENT = RequestLogger()


class Linkbots:
    """Container of Linbot instances."""
    bot_configs = app.config['LINKBOTS']
    bots = []

    def __init__(self):
        if not self.bots:
            for config in self.bot_configs:
                class_name = config.get('LINK_CLASS', 'LinkBot')
                bot_class = getattr(bots, class_name)
                try:
                    self.bots.append(bot_class(config))
                except Exception as e:
                    # report and swallow the error
                    app.logger.error(f'Error instantiating {class_name}: {e}')


    def __iter__(self):
        botlen, configlen = len(self.bots), len(self.bot_configs)
        if botlen != configlen:
            message = f'bot instances ({botlen}) != configs ({configlen})'
            app.logger.error(message)
        return iter(self.bots)


@app.route('/', methods=['GET', 'POST'])
def handle_message():
    """A single endpoint handling both events and commands."""
    if request.method == 'GET':
        return jsonify(success=True)  # to pass a health check

    verify_slack_signature()
    if not request.is_json:
        MessageProcessor.queue.put(partial(process_command, request.form))
        return jsonify(response_type='in_channel')
    json = request.get_json()
    if 'challenge' in json:
        # This is how Slack verifies our URL to receive events.
        return jsonify(challenge=json['challenge'])
    event = json['event']
    MessageProcessor.queue.put(partial(process_event, event))
    return '', 200


def verify_slack_signature():
    """
    Verify a slack signature according to
    https://api.slack.com/docs/verifying-requests-from-slack
    """
    if app.debug:
        return
    timestamp = request.headers['X-Slack-Request-Timestamp']
    signature = request.headers['X-Slack-Signature']
    if time.time() - int(timestamp) > 5 * 60:
        app.logger.error('Stale command request.')
        abort(403)
    compstr = f'v0:{timestamp}:'.encode() + request.get_data()
    rhash = hmac.new(SLACK_SECRET.encode(), compstr, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(f'v0={rhash}', signature):
        app.logger.error('Invalid X-Slack-Signature')
        abort(403)


class MessageProcessor(Thread):
    queue = Queue()

    def run(self):
        """Pull messages off the queue and process them."""
        while True:
            func = self.queue.get()
            try:
                func()
            except Exception as e:
                app.logger.exception(e)
            self.queue.task_done()


def process_event(event):
    """Process events by posting matches to the provided channel."""
    event_type = event.get('type')
    subtype = event.get('subtype')
    hidden = event.get('hidden')
    if event_type != 'message':
        app.logger.error(f'discarding unhandled event type {event_type}')
        return
    if 'bot_id' in event or subtype == 'bot_message':
        return

    event_keys = ','.join(event)
    description = f'subtype={subtype};hidden={hidden}, {event_keys}'
    if hidden or 'text' not in event or 'channel' not in event:
        app.logger.info(f'Event discarded: {description}')
        return
    text = event['text']
    post_args = {'channel': event['channel']}
    if 'thread_ts' in event:
        post_args['thread_ts'] = event['thread_ts']

    app.logger.debug(f'processing message from event: {description}')
    for message in links_from_text(text):
        SLACK_CLIENT.chat_postMessage(text=message, **post_args)


def process_command(command):
    """Process a slack command by posting a response to the provided url."""
    response_url = command.get('response_url')
    text = command.get('text')
    if not all([text, response_url]):
        command_keys = ','.join(command)
        app.logger.error(f'tossing supposed command: {command_keys}')
        return

    text = '\n'.join(links_from_text(text))
    if text:
        data = dict(text=text, response_type='in_channel')
        WEBHOOK_CLIENT.post(response_url, json=data)


def links_from_text(text):
    """Search for matches and post any to the original channel."""
    for bot in Linkbots():
        for match in bot.match(text):
            app.logger.info(f'{match} match!')
            try:
                yield bot.message(match)
            except Exception as e:
                app.logger.error(e)
                continue


for _ in range(4):
    MessageProcessor().start()
