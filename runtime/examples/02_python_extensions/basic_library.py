from dice import dicefunction


@dicefunction
def add_two(value):
    return value + 2


@dicefunction
def scale_damage(value, factor=2):
    return value * factor
