from dice import dice_interpreter, dicefunction
from diceengine import Distribution, Sweep


def build_result():
    session = dice_interpreter()

    @dicefunction
    def first_column(value: Sweep[Distribution]) -> Distribution:
        first_axis_value = value.axes[0].values[0]
        return value.cells[(first_axis_value,)]

    session.register_function(first_column)
    return session("first_column(d20 >= [AC:10..12])")
