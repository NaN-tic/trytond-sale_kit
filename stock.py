# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from trytond.i18n import gettext
from trytond.model import ModelView, Workflow, dualmethod, fields
from trytond.model.exceptions import AccessError
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval


_kit_shipments = ContextVar('sale_kit_shipments', default=frozenset())


@contextmanager
def synchronize_kit_shipments(shipments):
    """Authorize component changes only while processing their kit shipment."""
    token = _kit_shipments.set(
        _kit_shipments.get() | {s.id for s in shipments})
    try:
        yield
    finally:
        _kit_shipments.reset(token)


def kit_shipment_action(func):
    @wraps(func)
    def wrapper(cls, shipments, *args, **kwargs):
        cls._check_kit_control(shipments)
        with synchronize_kit_shipments(shipments):
            return func(cls, shipments, *args, **kwargs)
    return wrapper


def protect_component_fields(cls, parent_field):
    protected = Bool(Eval(parent_field))
    for name in dir(cls):
        if name.startswith('_'):
            continue
        field = getattr(cls, name)
        if not isinstance(field, fields.Field):
            continue
        field.states['readonly'] = (
            field.states.get('readonly', False) | protected)
    for button in cls._buttons.values():
        button['invisible'] = button.get('invisible', False) | protected


class Move(metaclass=PoolMeta):
    __name__ = 'stock.move'

    kit_parent_move = fields.Many2One(
        'stock.move', "Kit Move", readonly=True, ondelete='RESTRICT')
    kit_component_quantity = fields.Float(
        "Component Quantity per Kit Unit", readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        protect_component_fields(cls, 'kit_parent_move')

    @classmethod
    def _check_kit_control(cls, moves):
        Shipment = Pool().get('stock.shipment.out')
        for move in moves:
            parent = None
            shipment = getattr(move, 'shipment', None)
            if isinstance(shipment, Shipment):
                parent = shipment.kit_parent_shipment
            kit_move = getattr(move, 'kit_parent_move', None)
            if kit_move:
                parent = kit_move.shipment
            if parent and parent.id not in _kit_shipments.get():
                raise AccessError(gettext(
                        'sale_kit.msg_component_shipment_control',
                        shipment=parent.rec_name))

    @classmethod
    def check_modification(cls, mode, moves, values=None, external=False):
        cls._check_kit_control(moves)
        if values:
            cls._check_kit_control([cls(**{name: values[name]
                        for name in ('shipment', 'kit_parent_move')
                        if name in values})])
        super().check_modification(mode, moves, values, external=external)
        if not external:
            return
        Shipment = Pool().get('stock.shipment.out')
        for move in moves:
            if (isinstance(move.shipment, Shipment)
                    and move.shipment.kit_component_shipments
                    and move.product.kit
                    and (mode == 'delete'
                        or {'product', 'unit'} & set(values or {})
                        or (move.shipment.state != 'waiting'
                            and 'quantity' in (values or {})))):
                raise AccessError(gettext('sale_kit.msg_kit_move_change'))

    @classmethod
    def copy(cls, moves, default=None):
        cls._check_kit_control(moves)
        return super().copy(moves, default=default)


class ShipmentOut(metaclass=PoolMeta):
    __name__ = 'stock.shipment.out'

    kit_parent_shipment = fields.Many2One(
        'stock.shipment.out', "Kit Shipment", readonly=True,
        ondelete='RESTRICT')
    kit_component_shipments = fields.One2Many(
        'stock.shipment.out', 'kit_parent_shipment', "Component Shipments",
        readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        protect_component_fields(cls, 'kit_parent_shipment')

    @classmethod
    def check_modification(cls, mode, shipments, values=None, external=False):
        cls._check_kit_control(shipments)
        if values and values.get('kit_parent_shipment'):
            cls._check_kit_control([cls(
                        kit_parent_shipment=values['kit_parent_shipment'])])
        super().check_modification(
            mode, shipments, values, external=external)

    @classmethod
    def _check_kit_control(cls, shipments):
        for shipment in shipments:
            parent = shipment.kit_parent_shipment
            if parent and parent.id not in _kit_shipments.get():
                raise AccessError(gettext(
                        'sale_kit.msg_component_shipment_control',
                        shipment=parent.rec_name))

    @classmethod
    def _kit_children(cls, shipments):
        return [child for shipment in shipments
            for child in shipment.kit_component_shipments]

    @classmethod
    def _transition_kit_children(cls, shipments, transition):
        children = cls._kit_children(shipments)
        if children:
            with synchronize_kit_shipments(shipments):
                getattr(cls, transition)(children)

    def _kit_moves(self):
        SaleLine = Pool().get('sale.line')
        if self.kit_parent_shipment:
            return []
        return [m for m in self.outgoing_moves
            if isinstance(m.origin, SaleLine)
            and not m.origin.kit_parent_line and not m.origin.kit_child_lines
            and m.product.kit and m.product.stock_depends_on_kit_components
            and not m.product.explode_kit_in_sales
            and m.state not in {'cancelled', 'done', 'staging'}]

    def _create_kit_shipment(self):
        pool = Pool()
        Uom = pool.get('product.uom')
        Move = pool.get('stock.move')
        moves = []

        def components(product, quantity, unit, result):
            quantity = Uom.compute_qty(
                unit, quantity, product.default_uom, round=False)
            for line in product.kit_lines:
                component = line.product
                amount = quantity * line.quantity
                if component.kit and component.stock_depends_on_kit_components:
                    components(component, amount, line.unit, result)
                elif component.type == 'goods':
                    result[component] += Uom.compute_qty(
                        line.unit, amount, component.default_uom, round=False)

        for kit_move in self._kit_moves():
            quantities = defaultdict(float)
            components(kit_move.product, 1, kit_move.unit, quantities)
            for product, quantity in quantities.items():
                move = Move(
                    product=product, unit=product.default_uom,
                    quantity=product.default_uom.round(
                        kit_move.quantity * quantity),
                    from_location=self.warehouse_output,
                    to_location=self.customer_location,
                    company=self.company, planned_date=self.planned_date,
                    origin=kit_move, kit_parent_move=kit_move,
                    kit_component_quantity=quantity)
                if move.on_change_with_unit_price_required():
                    move.unit_price = product.cost_price
                    move.currency = self.company.currency
                moves.append(move)
        if moves:
            shipment = self.__class__(
                customer=self.customer, delivery_address=self.delivery_address,
                warehouse=self.warehouse, company=self.company,
                warehouse_storage=self.warehouse_storage,
                warehouse_output=self.warehouse_output,
                planned_date=self.planned_date, kit_parent_shipment=self,
                moves=moves)
            with synchronize_kit_shipments([self]):
                shipment.save()
                self.__class__.wait([shipment])

    def _get_inventory_move(self, move):
        inventory_move = super()._get_inventory_move(move)
        if inventory_move and move.kit_parent_move:
            inventory_move.kit_parent_move = move.kit_parent_move
            inventory_move.kit_component_quantity = move.kit_component_quantity
        return inventory_move

    @property
    def assign_moves(self):
        moves = tuple(super().assign_moves)
        for child in self.kit_component_shipments:
            if child.state not in {'done', 'cancelled'}:
                moves += tuple(child.assign_moves)
        return moves

    @classmethod
    def _remove_kit_shipments(cls, shipments):
        children = cls._kit_children(shipments)
        if children:
            with synchronize_kit_shipments(shipments):
                cls.cancel(children)
                cls.delete(children)

    @classmethod
    @ModelView.button
    @kit_shipment_action
    @Workflow.transition('waiting')
    def wait(cls, shipments, moves=None):
        cls._check_kit_control(shipments)
        cls._remove_kit_shipments(shipments)
        super().wait(shipments, moves=moves)
        for shipment in shipments:
            shipment._create_kit_shipment()

    @classmethod
    @ModelView.button
    @kit_shipment_action
    @Workflow.transition('draft')
    def draft(cls, shipments):
        cls._check_kit_control(shipments)
        cls._remove_kit_shipments(shipments)
        super().draft(shipments)

    def _kit_reservations(self):
        groups = defaultdict(list)
        for child in self.kit_component_shipments:
            for move in child.assign_moves:
                if move.state != 'cancelled':
                    groups[move.kit_parent_move, move.product].append(move)
        quantities = {}
        for (kit_move, product), moves in groups.items():
            if not moves[0].assignation_required:
                continue
            quantity = sum(m.quantity for m in moves if m.state == 'assigned')
            quantity /= moves[0].kit_component_quantity
            quantities[kit_move] = min(
                quantities.get(kit_move, kit_move.quantity),
                kit_move.unit.floor(quantity))
        return groups, quantities

    def _balance_kit_reservations(self):
        """Release components which cannot make a complete kit."""
        Move = Pool().get('stock.move')
        groups, quantities = self._kit_reservations()
        for (kit_move, product), moves in groups.items():
            remaining = (quantities.get(kit_move, kit_move.quantity)
                * moves[0].kit_component_quantity)
            for move in moves:
                if move.state != 'assigned':
                    continue
                keep = move.unit.round(min(remaining, move.quantity))
                remaining = max(0, remaining - keep)
                if keep < move.quantity:
                    quantity = move.quantity
                    Move.draft([move])
                    if keep:
                        Move.copy([move], default={
                                'quantity': move.unit.round(quantity - keep),
                                'state': 'draft',
                                })
                        Move.write([move], {'quantity': keep})
                        Move.assign([move])

    def _sync_kit_quantities(self):
        """Rebuild reservations after editing the requested kit quantity."""
        Move = Pool().get('stock.move')
        Uom = Pool().get('product.uom')
        demands = defaultdict(float)
        for child in self.kit_component_shipments:
            for move in child.outgoing_moves:
                demands[move.kit_parent_move, move.product] += (
                    move.quantity / move.kit_component_quantity)
        changed = False
        for kit_move in self._kit_moves():
            previous = next((q for (parent, _), q in demands.items()
                    if parent == kit_move), kit_move.quantity)
            quantity = kit_move.quantity
            if self.warehouse_storage != self.warehouse_output:
                inventory_quantity = sum(Uom.compute_qty(
                        m.unit, m.quantity, kit_move.unit, round=False)
                    for m in self.inventory_moves if m.origin == kit_move)
                if quantity == previous and inventory_quantity != previous:
                    quantity = inventory_quantity
            if kit_move.unit.round(quantity - previous):
                Move.draft([kit_move])
                Move.write([kit_move], {'quantity': quantity})
                changed = True
        if changed:
            self.__class__.wait([self])

    @dualmethod
    @ModelView.button
    @kit_shipment_action
    def assign_try(cls, shipments):
        cls._check_kit_control(shipments)
        Move = Pool().get('stock.move')
        regular = []
        for shipment in shipments:
            if shipment.state != 'waiting':
                continue
            if not shipment.kit_component_shipments:
                shipment._create_kit_shipment()
            if not shipment.kit_component_shipments:
                regular.append(shipment)
                continue
            shipment._sync_kit_quantities()
            Move.assign_try([m for m in shipment.assign_moves
                    if m.assignation_required and not m.kit_parent_move])
            for kit_move in shipment._kit_moves():
                Move.assign_try([m for m in shipment.assign_moves
                        if m.kit_parent_move == kit_move
                        and m.assignation_required])
                shipment._balance_kit_reservations()
            if not any(m.state in {'draft', 'staging'}
                    for m in shipment.assign_moves
                    if m.assignation_required and m.quantity):
                cls.assign([shipment])
        if regular:
            super().assign_try(regular)

    @dualmethod
    @kit_shipment_action
    def assign_ignore(cls, shipments, moves=None):
        cls._check_kit_control(shipments)
        Move = Pool().get('stock.move')
        Uom = Pool().get('product.uom')
        for shipment in shipments:
            groups, quantities = shipment._kit_reservations()
            selected = set(moves) if moves is not None else None
            for kit_move, quantity in quantities.items():
                component_moves = [m for (parent, _), group in groups.items()
                    if parent == kit_move for m in group]
                if (selected is not None
                        and not selected.intersection(component_moves)):
                    continue
                # Keep the commercial move as the sole source of delivered
                # and invoiceable quantities. Sale processing creates the rest.
                Move.draft([kit_move])
                Move.write([kit_move], {'quantity': quantity})
                remaining = quantity
                for move in shipment.inventory_moves:
                    if move.origin == kit_move:
                        keep = min(move.quantity, Uom.compute_qty(
                                kit_move.unit, remaining, move.unit))
                        remaining -= Uom.compute_qty(
                            move.unit, keep, kit_move.unit)
                        Move.draft([move])
                        Move.write([move], {'quantity': keep})
                        Move.assign([move])
                if shipment.warehouse_storage == shipment.warehouse_output:
                    Move.assign([kit_move])
                for move in component_moves:
                    if move.state in {'draft', 'staging'}:
                        Move.write([move], {'quantity': 0})
                for child in shipment.kit_component_shipments:
                    if child.warehouse_storage != child.warehouse_output:
                        for move in child.outgoing_moves:
                            if move.kit_parent_move == kit_move:
                                Move.write([move], {'quantity': move.unit.round(
                                            quantity
                                            * move.kit_component_quantity)})
        super().assign_ignore(shipments, moves=moves)

    @classmethod
    @kit_shipment_action
    @Workflow.transition('assigned')
    def assign(cls, shipments):
        cls._check_kit_control(shipments)
        cls._transition_kit_children(shipments, 'assign')
        super().assign(shipments)

    @dualmethod
    @ModelView.button
    @kit_shipment_action
    def assign_force(cls, shipments):
        cls._check_kit_control(shipments)
        for shipment in shipments:
            shipment._sync_kit_quantities()
        super().assign_force(shipments)

    @classmethod
    @ModelView.button
    @kit_shipment_action
    @Workflow.transition('picked')
    def pick(cls, shipments):
        cls._check_kit_control(shipments)
        cls._transition_kit_children(shipments, 'pick')
        super().pick(shipments)

    @classmethod
    @ModelView.button
    @kit_shipment_action
    @Workflow.transition('packed')
    def pack(cls, shipments):
        cls._check_kit_control(shipments)
        cls._transition_kit_children(shipments, 'pack')
        super().pack(shipments)

    @classmethod
    @ModelView.button
    @kit_shipment_action
    @Workflow.transition('shipped')
    def ship(cls, shipments):
        cls._check_kit_control(shipments)
        cls._transition_kit_children(shipments, 'ship')
        super().ship(shipments)

    @classmethod
    @ModelView.button
    @kit_shipment_action
    @Workflow.transition('done')
    def do(cls, shipments):
        cls._check_kit_control(shipments)
        cls._transition_kit_children(shipments, 'do')
        super().do(shipments)

    @classmethod
    @ModelView.button
    @kit_shipment_action
    @Workflow.transition('cancelled')
    def cancel(cls, shipments):
        cls._check_kit_control(shipments)
        cls._remove_kit_shipments(shipments)
        super().cancel(shipments)

    @classmethod
    @kit_shipment_action
    def delete(cls, shipments):
        cls._check_kit_control(shipments)
        cls._remove_kit_shipments(shipments)
        super().delete(shipments)

    @classmethod
    def copy(cls, shipments, default=None):
        cls._check_kit_control(shipments)
        default = dict(default or {})
        default.setdefault('kit_parent_shipment', None)
        default.setdefault('kit_component_shipments', None)
        return super().copy(shipments, default=default)


class AssignPartial(metaclass=PoolMeta):
    __name__ = 'stock.shipment.assign.partial'

    kit_summary = fields.Text("Kit Reservations", readonly=True,
        states={'invisible': ~Eval('kit_summary')})


class Assign(metaclass=PoolMeta):
    __name__ = 'stock.shipment.assign'

    def default_partial(self, fields):
        values = super().default_partial(fields)
        pool = Pool()
        Shipment = pool.get('stock.shipment.out')
        Lang = pool.get('ir.lang')
        if 'kit_summary' in fields and isinstance(self.record, Shipment):
            lang = Lang.get()
            _, quantities = self.record._kit_reservations()
            values['kit_summary'] = '\n'.join(gettext(
                    'sale_kit.msg_kit_reservation', kit=move.product.rec_name,
                    requested=lang.format_number_symbol(
                        move.quantity, move.unit),
                    reserved=lang.format_number_symbol(quantity, move.unit))
                for move, quantity in quantities.items())
        return values
