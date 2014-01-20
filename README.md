
Repeat
======

Example code for Simon-like game for Raspberry Pi using straight GPIO. Sound is
output using the sound device available to pygame.

I, Peter S. May, the author, hereby release the code and sound files for this
project into the public domain, as-is, without the faintest shadow of a
warranty.


Circuit
-------

Connect buttons from GPIO 4, 18, 23, 17 (clockwise order) to ground. Internal
pull-up resistors are used, so separate pull-ups are not needed.

Connect the anodes of the respective LEDs to 27, 24, 25, 22. Connect each
cathode through an appropriate series resistor (accounting for 3.3V input) to
ground.

