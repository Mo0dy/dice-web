from dice import dice_interpreter, dicefunction


def build_result():
    session = dice_interpreter()

    @dicefunction
    def add_two(value):
        return value + 2

    session.register_function(add_two)
    return session("add_two([1..3])")
