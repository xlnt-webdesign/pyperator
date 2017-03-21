from .nodes import Component


class GeneratorSource(Component):
    """
    This is a component that returns a single element from a generator
    to a single output
    """
    def __init__(self, name, generator, outputs=[]):
        super(GeneratorSource,self).__init__(name, generator, inputs=[], outputs=outputs)
        self._gen = generator

    async def __call__(self):
        #We dont need to wait for incoming data
        gen_output = next(self._gen)
        #We call the generator and send
        transformed = {out_name: gen_output for out_name, out_port in self.outports}
        await self.send(transformed)



class GeneratorZipper(Component):
