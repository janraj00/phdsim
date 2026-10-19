'Enforce budgets and charge each transfer once.'
from __future__ import annotations

from collections.abc import Iterable

from .types import CostComponent, CostVector

def validate_cost_schema(cost: CostVector, template: CostVector) -> None:
    if {c.name for c in cost.components} != {c.name for c in template.components}:
        raise ValueError('Cost components differ from the declared schema')
    for expected in template.components:
        actual = cost.get(expected.name)
        assert actual is not None
        if actual.unit != expected.unit:
            raise ValueError(f'Incompatible units for {expected.name}')
        if (actual.status == 'excluded') != (expected.status == 'excluded'):
            raise ValueError(f'Experiment scope changed for {expected.name}')

def sum_costs(vectors: Iterable[CostVector], template: CostVector) -> CostVector:
    values = tuple(vectors)
    for vector in values:
        validate_cost_schema(vector, template)
    total = []
    for component in template.components:
        parts = [vector.get(component.name) for vector in values]
        if component.status == 'excluded':
            total.append(component)
        elif any((part is not None and part.value is None for part in parts)):
            total.append(CostComponent(component.name, component.unit, None, 'unmeasured'))
        elif not parts and component.status == 'unmeasured':
            total.append(component)
        else:
            measured = sum((part.value for part in parts if part is not None and part.value is not None))
            total.append(CostComponent(component.name, component.unit, measured))
    return CostVector(tuple(total))

class CostLedger:

    def __init__(self, budget: CostVector, template: CostVector) -> None:
        for limit in budget.components:
            component = template.get(limit.name)
            if limit.status != 'included' or component is None or component.status == 'excluded':
                raise ValueError('Budgets require an included cost component')
            if component.unit != limit.unit:
                raise ValueError('Budget and cost units differ')
        self.budget = budget
        self.template = template
        self._charges: dict[str, CostVector] = {}
        self._total = sum_costs((), self.template)

    @property
    def total(self) -> CostVector:
        return self._total

    def refusal_reason(self, estimate: CostVector) -> str | None:
        validate_cost_schema(estimate, self.template)
        total = self.total
        for limit in self.budget.components:
            used = total.get(limit.name)
            expected = estimate.get(limit.name)
            assert used is not None and expected is not None and (limit.value is not None)
            if used.value is None or expected.value is None:
                return 'budget_unverifiable'
            if used.value + expected.value > limit.value + 1e-12:
                return 'budget_blocked'
        return None

    def charge(self, execution_id: str, cost: CostVector) -> bool:
        validate_cost_schema(cost, self.template)
        if execution_id in self._charges:
            if self._charges[execution_id] != cost:
                raise ValueError('Execution id has conflicting cost reports')
            return False
        self._total = sum_costs((self._total, cost) if self._charges else (cost,), self.template)
        self._charges[execution_id] = cost
        return True

    def remaining(self) -> CostVector:
        total = self.total
        remaining = []
        for limit in self.budget.components:
            used = total.get(limit.name)
            assert used is not None and limit.value is not None
            if used.value is None:
                remaining.append(CostComponent(limit.name, limit.unit, None, 'unmeasured'))
            else:
                remaining.append(CostComponent(limit.name, limit.unit, max(0.0, limit.value - used.value)))
        return CostVector(tuple(remaining))

    def terminal_reason(self) -> str | None:
        total = self.total
        exhausted = False
        for limit in self.budget.components:
            used = total.get(limit.name)
            assert used is not None and limit.value is not None
            if used.value is None:
                return 'budget_unknown'
            if used.value > limit.value + 1e-12:
                return 'budget_overrun'
            exhausted |= used.value >= limit.value - 1e-12
        return 'budget_exhausted' if exhausted else None
