#!/usr/bin/env python
# vim: set fileencoding=utf8 :

# repeat.py
# GPIO and sound example for Raspberry Pi
# Written by Peter S. May for the public domain
# Refer to README.md for details

import sys
import pygame.mixer
import pygame.time
import RPi.GPIO as GPIO
import collections
import random
from Queue import Queue
from threading import Timer


# Classes/Types
# -------------

# A Position is data about one button/light. It is defined with these
# parameters:
# - soundName: The basename for the WAV file for the beep from this position
# - inPin: The GPIO number of the pin connected to the button for this position
# - outPin: The GPIO number of the pin connected to the LED for this position
# - sequenceLength: When button is pressed during attract mode, the number of
#   moves needed to win
Position = collections.namedtuple('Position', 'soundName inPin outPin sequenceLength')

# A State is just an object that holds a value in the mutable attribute
# value. It's used here to make it possible to mutate non-global variables
# from inside a nested function. (Python 3 has the nonlocal keyword to
# accomplish the same more neatly.)
class State(object):
	__slots__ = 'value'
	def __init__(self, value=None):
		self.value = value
	def __nonzero__(self):
		return bool(self.value)


# Predefined constant-like values
# -------------------------------

# Positions for available buttons
_positions = [
	Position('s1', 4, 27, 4),
	Position('s2', 18, 24, 8),
	Position('s3', 23, 25, 16),
	Position('s4', 17, 22, 32),
]

# Basename for the WAV file corresponding to an incorrect move
WRONG_SOUND_NAME = 'lose'


# Support functions
# -----------------

_cachedSounds = {}
def makeSound(soundName, preloadOnly=False):
	"""
	Loads a sound by the basename of its WAV file, caching the result for
	repeated reads. Plays the sound unless preloadOnly.

	Returns the Sound object.
	"""
	if soundName not in _cachedSounds:
		_cachedSounds[soundName] = pygame.mixer.Sound("sound/%s.wav" % soundName)
	sound = _cachedSounds[soundName]
	if not preloadOnly:
		sound.play()
	return sound

def delay(duration):
	"""Pauses this thread by the given number of milliseconds."""
	# wait causes the process to sleep.
	return pygame.time.wait(duration)
	# delay attempts to be more precise by busy-waiting.
	# return pygame.time.delay(duration)

def getRandomPosition():
	"""Generates a pseudorandom position index."""
	return random.randrange(len(_positions))

def lightOnly(index):
	"""
	Turns on the light for the given position; turns off the light for all
	others. If index is None (or not a position), all are turned off. Returns
	the matched index, if any, or None otherwise.
	"""
	lit = None
	for positionIndex, position in enumerate(_positions):
		matched = (positionIndex == index)
		GPIO.output(position.outPin, matched)
		if matched:
			lit = positionIndex
	return lit

def activate(index, correct=True):
	"""
	Light only the given index, and also play its corresponding sound. If not
	correct, play the fail sound instead.

	Note that the sound playing mechanism is asynchronous, so any necessary
	delay needed to allow the sound to play must be performed explicitly.
	"""
	lit = lightOnly(index)
	makeSound(_positions[lit].soundName if correct else WRONG_SOUND_NAME)

def deactivate():
	"""Unlight all positions."""
	lightOnly(None)

def startSoundMixer():
	"""Starts sound mixer."""
	# The buffer size has to be set lower than the default (4096) in order to
	# decrease latency. Otherwise, the sounds and lights don't match well.
	pygame.mixer.init(frequency=22050, size=-8, channels=2, buffer=512)

def preloadSounds():
	"""Pre-fetches known sound samples."""
	for soundName in [position.soundName for position in _positions] + [WRONG_SOUND_NAME]:
		makeSound(soundName, False)

_inPinToPositionIndex = {}
def preMapInputPinsToPositions():
	"""Generates mapping of input pins to their positions."""
	for index, position in enumerate(_positions):
		_inPinToPositionIndex[position.inPin] = index

def getPositionForPin(pin):
	"""Returns position associated with pin number."""
	return _inPinToPositionIndex[pin]


# Events machinery
# ----------------

# In this program, timeouts and button presses and releases result in callbacks
# being called in separate threads. The callbacks we use each deposit a value
# in events, which is a Queue—Python's basic synchronized blocking queue. The
# main thread can then simply wait on events to happen and process them in
# order.
_events = Queue()

def clearEvents():
	"""Discard any information about pending events."""
	with _events.mutex:
		_events.queue.clear()

def waitForEvents(timeout, callback):
	"""
	Calls a callback for each button event that appears in the queue,
	continuing until the callback returns true. If timeout is defined, also
	schedules a task to add a timeout event to the queue after the given delay
	(in ms), and returns if that timeout event is processed before a call to
	the callback returns true.

	Returns true if the loop ended because a call to the callback returned
	true, or false if the loop ended because of the timeout event.
	"""
	ourTimer = None
	ourTimeoutMarker = None

	if timeout is not None:
		# This dummy object helps to check whether a timeout event was actually
		# generated by this call. (It's theoretically possible that a stale
		# timeout event from a previous call is still in the queue.)
		ourTimeoutMarker = object()

		# Schedule a timeout event to be added from another thread.
		def onTimeout():
			_events.put((None, ourTimeoutMarker))

		ourTimer = Timer(timeout / 1000.0, onTimeout)
		ourTimer.start()

	# Watch the events queue.
	while True:
		index, value = _events.get()
		if index is None and value is ourTimeoutMarker:
			# Got timeout event
			return False
		elif index is not None and callback(index, value):
			if ourTimer is not None:
				ourTimer.cancel()
			# Callback returned true; the event was handled and exits the loop.
			return True
		# else, stale timeout or event was not handled; keep going

def waitForButtonEvent(timeout=None, value=None):
	"""
	Waits for any event for any button, or for a timeout. If value is given,
	events not matching that value are discarded. Returns None on timeout;
	otherwise, returns the index of the changed position.
	"""
	buttonValue = State(None)
	def callback(index, in_value):
		if index is not None and (value is None or value == in_value):
			buttonValue.value = index
			return True
		return False
	waitForEvents(timeout, callback)
	return buttonValue.value

def waitForButtonPress(timeout=None):
	"""Waits for a press event for any button, or for a timeout."""
	return waitForButtonEvent(timeout, True)

def waitForButtonRelease(timeout=None):
	"""Waits for a release event for any button, or for a timeout."""
	return waitForButtonEvent(timeout, False)


# Direct button handling
# ----------------------

_currentButton = State(None)
def processEvent(pin):
	"""
	GPIO edge callback to produce button events for the queue.

	Both edges are watched so that the event shows up at least once per press
	or release. The program is not fast enough to distinguish which edge
	appeared all of the time, and software debounce makes the response sluggish
	(in this case). So, the event processing applies some simple (yet not fully
	goof-proof) logic to determine whether we think the state has changed.

	- An edge only triggers a check; whether or not the button is down depends
	  on its GPIO.input() value.
	- The game only considers at most one button to be pressed at any time. If
	  a button is already down, any new button events are discarded except for
	  a release event from the same button.

	Only those events not discarded above are added to the queue.
	"""

	index = getPositionForPin(pin)
	# Since 'pressed' is false, invert.
	value = not GPIO.input(pin)

	if _currentButton.value is None and value:
		# New button is pressed.
		_currentButton.value = index
	elif _currentButton.value == index and not value:
		# Current button is released.
		_currentButton.value = None
	else:
		# If the event is for a press of a button when a button is already
		# down, or for the release of the button that isn't the currently down
		# button, it is ignored.
		return None

	_events.put((index, value))
	return value


# Game
# ----


def attractLoop(waitFirst=None):
	"""
	Play an attract pattern while waiting for the player to start the game. Any
	button press starts the game, but the position determines the sequence
	length (the number of moves needed to win).

	If waitFirst is provided, the pattern will not begin playing for waitFirst
	ms, but it will still be possible to start a new game. (This is used to
	provide the delay between the end of a game and the beginning of the
	attract pattern.)

	Returns the selected sequence length.
	"""
	button = None

	if waitFirst is not None:
		deactivate()
		button = waitForButtonPress(waitFirst)

	while button is None:
		for index, position in enumerate(_positions):
			if button is not None:
				break
			activate(index)
			button = waitForButtonPress(250)
		if button is not None:
			break
		deactivate()
		button = waitForButtonPress(5000)

	sequenceLength = _positions[button].sequenceLength
	print "Will start game with sequence length = %s" % sequenceLength
	return sequenceLength

def gameLoop(sequenceLength):
	"""Play an actual game using the given sequence length."""

	# List of indices played by the CPU.
	sequence = []

	waitForNextRound = False

	while len(sequence) < sequenceLength:
		# Generate the next move and add it to the list.
		sequence.append(getRandomPosition())

		# A delay is inserted between rounds, but not before the first or after
		# the last.
		if waitForNextRound:
			delay(1000)
		else:
			waitForNextRound = True

		# Play back current sequence.
		for index in sequence:
			activate(index)
			delay(250)
			deactivate()
			delay(250)

		# Discard any presses that may have happened during playback.
		clearEvents()

		# Read in sequence
		for index in sequence:
			button = waitForButtonPress(3000)
			if button == index:
				# Correct
				activate(index)
				waitForButtonRelease()
				deactivate()
			else:
				# Very not correct
				activate(index, False)
				delay(1500)
				deactivate()
				delay(2000)
				return False

	# It's a win.
	delay(500)
	victoryBoogie()
	return True

def victoryBoogie():
	"""Displays a celebratory animation."""
	for index in (0, 1, 0, 1, 2, 1, 2, 3, 2, 3):
		activate(index)
		delay(125)
	deactivate()
	clearEvents()


# Entry points
# ------------

def mainLoop():
	"""Sets up GPIO and sound, then alternates between attract and game sequences."""

	startSoundMixer()
	preloadSounds()
	preMapInputPinsToPositions()

	for position in _positions:
		# Inputs are pulled up so no external pullup is necessary
		GPIO.setup(position.inPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
		GPIO.add_event_detect(position.inPin, GPIO.BOTH, callback=processEvent)
		GPIO.setup(position.outPin, GPIO.OUT, initial=False)

	sequenceLength = attractLoop(0)
	while True:
		gameLoop(sequenceLength)
		sequenceLength = attractLoop(5000)

def main(args):
	"""Runs the main program."""
	# This try block causes GPIO.cleanup() to execute no matter whether mainLoop()
	# exits by a normal return or a thrown exception (such as a KeyboardInterrupt
	# resulting from pressing ctrl-C). Because the lifetime of the systemwide GPIO
	# on the Pi is longer than the lifetime of this program, and because other
	# programs might share it, this cleanup bit is actually pretty necessary.
	#
	# All of the code that actually uses GPIO is squirreled away into mainLoop() so
	# that the extra level of nesting from this block might be either avoided or
	# made clearer. If a bit of code ever gets to be too long (say, more than one
	# screenful) or too deep (say, four or five indents), seriously consider
	# refactoring parts of it into separate functions.
	try:
		GPIO.setmode(GPIO.BCM)
		mainLoop()
	finally:
		GPIO.cleanup()

# This is a convention used to prevent the main code from running if this file
# is loaded as a library instead of a program. It's not strictly necessary here
# but it may be worth developing the habit of including it.
if __name__ == "__main__":
	main(sys.argv)

