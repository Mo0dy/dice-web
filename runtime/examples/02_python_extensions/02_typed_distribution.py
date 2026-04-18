from dice import dice_interpreter, dicefunction
from diceengine import Distribution


def build_result():
    session = dice_interpreter()

    @dicefunction
    def increment(value: Distribution) -> Distribution:
        return Distribution((outcome + 1, probability) for outcome, probability in value.items())

    session.register_function(increment)
    return session("increment([1..3])")
