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
import random
from Queue import Queue
from threading import Timer

Position = collections.namedtuple('Position', 'soundName inPin outPin')
class State(object):
	__slots__ = 'value'
	def __init__(self, value=None):
		self.value = value
	def __nonzero__(self):
		return bool(self.value)

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

# Number of turns needed to win
MAX_SEQUENCE = 5

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

# Random number generation
def getRandomPosition():
	return random.randrange(len(positions))

# Resynchronized button events

events = Queue()

def clearEvents():
	with events.mutex:
		events.queue.clear()

def waitForEvents(timeout, callback):
	shouldStillTimeout = True
	ourTimer = None
	ourTimeoutMarker = object()

	if timeout is not None:
		# Schedule a timeout event to be added from another thread.
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
		elif index is not None and callback(index, value):
			# Best effort to cancel the timeout event (should be harmless if it
			# slips through)
			shouldStillTimeout = False
			if ourTimer is not None:
				ourTimer.cancel()
			# Callback returned true; the event was handled and exits the loop.
			return True
		# else, stale timeout or event was not handled; keep going

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

def lightOnly(index):
	lit = None
	for pi, position in enumerate(positions):
		GPIO.output(position.outPin, pi == index)
		lit = pi
	return lit

def lightClear():
	lightOnly(None)

def lightBeep(index):
	lit = lightOnly(index)

def lightBuzz(index):
	lit = lightOnly(index)

def attractLoop(waitFirst=None):
	attracting = State(True)

	def stopAttracting(index, value):
		if value:
			attracting.value = False
			return True
		return False

	if waitFirst is not None:
		lightClear()
		waitForEvents(waitFirst, stopAttracting)

	while attracting:
		for pi, position in enumerate(positions):
			if not attracting:
				break
			lightBeep(pi)
			waitForEvents(250, stopAttracting)
		if not attracting:
			break
		lightClear()
		waitForEvents(5000, stopAttracting)

def processRelease(index, value):
	if index is not None and not value:
		return True
	return False

def gameLoop():
	sequence = []

	waitForNextRound = False

	while len(sequence) < MAX_SEQUENCE:
		sequence.append(getRandomPosition())

		if waitForNextRound:
			delay(1000)
		else:
			waitForNextRound = True

		# Play back current sequence
		for pi in sequence:
			lightBeep(pi)
			delay(250)
			lightClear()
			delay(250)
		lightClear()

		# Get rid of any presses that happened during playback
		clearEvents()

		buttonValue = State(None)
		def interpretButton(index, value):
			if value:
				buttonValue.value = index
				return True
			return False

		# Read in sequence
		for pi in sequence:
			waitForEvents(3000, interpretButton)
			if buttonValue.value == pi:
				# Correct
				lightBeep(pi)
				waitForEvents(None, processRelease)
				lightClear()
			else:
				# Very not correct
				lightBuzz(pi)
				delay(1500)
				lightClear()
				delay(2000)
				return False

	# It's a win.
	delay(500)
	victoryBoogie()
	return True

def victoryBoogie():
	for pi in (0, 1, 0, 1, 2, 1, 2, 3, 2, 3):
		lightBeep(pi)
		delay(250)
	lightClear()
	clearEvents()

def mainLoop():
	for position in positions:
		# Inputs are pulled up so no external pullup is necessary
		GPIO.setup(position.inPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
		GPIO.add_event_detect(position.inPin, GPIO.BOTH, callback=processEvent)
		GPIO.setup(position.outPin, GPIO.OUT, initial=False)

	attractLoop(0)
	while True:
		gameLoop()
		attractLoop(5000)

try:
	GPIO.setmode(GPIO.BCM)
	mainLoop()
finally:
	GPIO.cleanup()

