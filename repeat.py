#!/usr/bin/env python

# NOTE: This version is not the complete implementation!

# repeat.py
# GPIO and sound example for Raspberry Pi
# Written by Peter S. May for the public domain
# Refer to README.md for details

import pygame.mixer as mixer
import pygame.time
import RPi.GPIO as GPIO
import collections
from Queue import Queue
from threading import Timer

Position = collections.namedtuple('Position', 'soundName inPin outPin')

# Start sound mixer
mixer.init()

# Sounds and pins corresponding to buttons/lights
positions = [
	Position('s1', 4, 27),
	Position('s2', 18, 24),
	Position('s3', 23, 25),
	Position('s4', 17, 22),
]

# Sound corresponding to wrong answer
WRONG = Position('lose', None, None)


cachedSounds = {}

def getSound(soundName):
	if soundName not in cachedSounds:
		cachedSounds[soundName] = mixer.Sound("sound/%s.wav" % soundName)
	return cachedSounds[soundName]

# Preload sounds
for position in positions + [WRONG]:
	getSound(position.soundName)

# Placeholders for time manipulation

def ticks():
	return pygame.time.get_ticks()

def delay(duration):
	# wait causes the process to sleep.
	return pygame.time.wait(duration)
	# delay attempts to be more precise by busy-waiting.
	# return pygame.time.delay(duration)

# Map input pin back to position
inPinToPositionIndex = {}
for index, position in enumerate(positions):
	inPinToPositionIndex[position.inPin] = index


# Resynchronized button events

events = Queue()

def clearEvents():
	with events.mutex:
		events.queue.clear()

def waitForEvents(timeout, callback):
	# Schedule a timeout event to be added from another thread.
	shouldStillTimeout = True
	ourTimeoutMarker = object()
	def onTimeout():
		if shouldStillTimeout:
			events.put((None, ourTimeoutMarker))

	ourTimer = Timer(timeout / 1000.0, onTimeout)
	ourTimer.start()

	# Watch the events queue.
	while True:
		index, value = events.get()
		if index is None and value is ourTimeoutMarker:
			# Got timeout
			return False
		elif index is not None and not callback(index, value):
			# Best effort to cancel the timeout event (should be harmless if it
			# slips through)
			shouldStillTimeout = False
			ourTimer.cancel()
			# Callback returned false; not a timeout.
			return True
		# else, stale timeout or callback returned true; keep going

# Both edges are watched so that the event shows up at least once per press or
# release. The program is not fast enough to distinguish which edge appeared
# all of the time, and software debounce makes the response sluggish (in this
# case). So, the event processing applies some simple (yet not fully
# goof-proof)) logic to determine whether we think the state has changed.
# Button events and timeouts originate from separate threads and come together
# into a thread-safe blocking queue, which is then used to run the game
# synchronously.
currentButton = None
def processEvent(pin):
	global currentButton
	index = inPinToPositionIndex[pin]
	# Since 'pressed' is false, invert.
	value = not GPIO.input(pin)

	if currentButton is None and value:
		# New button is pressed.
		currentButton = index
	elif currentButton == index and not value:
		# Current button is released.
		currentButton = None
	else:
		# If the event is for a press of a button when a button is already
		# down, or for the release of the button that isn't the currently down
		# button, it is ignored.
		return None

	events.put((index, value))
	return value

def mainLoop():
	for position in positions:
		# Inputs are pulled up so no external pullup is necessary
		GPIO.setup(position.inPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
		GPIO.add_event_detect(position.inPin, GPIO.BOTH, callback=processEvent)
		GPIO.setup(position.outPin, GPIO.OUT, initial=False)

	def cb(index, value):
		print "Got event %s -> %s" % (index, value)
		return True

	for outPin in (x.outPin for x in positions):
		GPIO.output(outPin, True)
		delay(500)

	print "Waiting"
	rv = waitForEvents(10000, cb)
	print "Done waiting (%s)" % (rv)

try:
	GPIO.setmode(GPIO.BCM)
	mainLoop()
finally:
	GPIO.cleanup()

