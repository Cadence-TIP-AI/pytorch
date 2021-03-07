from typing import List, Dict, Optional
import torch
import torch.optim._functional as F

from torch import Tensor

# Define a TorchScript compatible Functional RMSprop Optimizer
# where we use these optimizer in a functional way.
# Instead of using the `param.grad` when updating parameters,
# we explicitly allow the distributed optimizer pass gradients to
# the `step` function. In this way, we could separate the gradients
# and parameters and allow multithreaded trainer to update the
# parameters without data traces on accumulating to the same .grad.
# NOTE: This should be only used by distributed optimizer internals
# and not meant to expose to the user.
@torch.jit.script
class _FunctionalRMSprop(object):
    def __init__(
        self,
        params: List[Tensor],
        lr: float = 1e-2,
        alpha: float = 0.99,
        eps: float = 1e-8,
        weight_decay: float = 0.0,
        momentum: float = 0.0,
        centered: bool = False
    ):
        self.defaults = {
            "lr": lr,
            "alpha": alpha,
            "eps": eps,
            "weight_decay": weight_decay,
            "momentum": momentum,
        }
        self.centered = centered

        if len(params) == 0:
            raise ValueError("optimizer got an empty parameter list")

        # NOTE: we only have one param_group and don't allow user to add additional
        # param group as it's not a common use case.
        self.param_group = {"params": params}

        self.state = torch.jit.annotate(Dict[torch.Tensor, Dict[str, torch.Tensor]], {})

    def step(self, gradients: List[Optional[Tensor]]):
        params = self.param_group['params']
        grads = []
        square_avgs = []
        grad_avgs = []
        momentum_buffer_list = []
        lr = self.defaults['lr']
        alpha = self.defaults['alpha']
        eps = self.defaults['eps']
        momentum = self.defaults['momentum']
        weight_decay = self.defaults['weight_decay']

        if len(params) != len(gradients):
            raise ValueError(
                "the gradients passed in does not equal to the size of the parameters!"
                + f"Params length: {len(params)}. "
                + f"Gradients length: {len(gradients)}"
            )

        for param, gradient in zip(params, gradients):
            if gradient is not None:
                grads.append(gradient)
                # Lazy state initialization
                if param not in self.state:
                    self.state[param] = {}
                    state = self.state[param]
                    state['step'] = torch.tensor(0.0)
                    state['square_avg'] = torch.zeros_like(param, memory_format=torch.preserve_format)
                    if momentum > 0:
                        state['momentum_buffer'] = torch.zeros_like(param, memory_format=torch.preserve_format)
                    if self.centered:
                        state['grad_avg'] = torch.zeros_like(param, memory_format=torch.preserve_format)

                state = self.state[param]
                square_avgs.append(state['square_avg'])
                if momentum > 0:
                    momentum_buffer_list.append(state['momentum_buffer'])
                if self.centered:
                    grad_avgs.append(state['grad_avg'])

                state['step'] += 1

        with torch.no_grad():
            F.rmsprop(params,
                      grads,
                      square_avgs,
                      grad_avgs,
                      momentum_buffer_list,
                      lr,
                      alpha,
                      eps,
                      weight_decay,
                      momentum,
                      self.centered)
