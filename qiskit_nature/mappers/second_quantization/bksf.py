# This code is part of Qiskit.
#
# (C) Copyright IBM 2021.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""The Bravyi-Kitaev Super Fast Mapper."""

from typing import List
import numpy as np

from qiskit.opflow import PauliSumOp
from qiskit.quantum_info.operators import Pauli, SparsePauliOp
from qiskit_nature.operators.second_quantization import FermionicOp
from .fermionic_mapper import FermionicMapper


def _pauli_id(n_qubits: int):
    """
    Return an `n_qubits`-identity `SparsePauliOp`.
    """
    return SparsePauliOp(Pauli((np.zeros(n_qubits, dtype=bool), np.zeros(n_qubits, dtype=bool))))


def _number_operator(edge_list: List, p: int, h1_pq: float):  # pylint: disable=invalid-name
    b_p = edge_operator_bi(edge_list, p)
    id_op = _pauli_id(edge_list.shape[1])
    qubit_op = (0.5 * h1_pq) * (id_op - b_p)  # SW2018 eq 33
    return qubit_op


## SW2018 eq 34
def _coulomb_exchange(
    edge_list: List, p: int, q: int, s: int, h2_pqrs: float
):  # pylint: disable=invalid-name
    b_p = edge_operator_bi(edge_list, p)
    b_q = edge_operator_bi(edge_list, q)
    id_op = _pauli_id(edge_list.shape[1])
    qubit_op = (id_op - b_p) * (id_op - b_q)
    if p == s:  # two commutations
        final_coeff = 0.25
    else:  # one commutation
        final_coeff = -0.25
    qubit_op = (final_coeff * h2_pqrs) * qubit_op
    return qubit_op


## SW2018 eq 35
## Includes contributions from a h.c. pair
def _excitation_operator(
    edge_list: List, p: int, q: int, h1_pq: float
):  # pylint: disable=invalid-name
    if p >= q:
        raise ValueError("Expected p < q, got p = ", p, ", q = ", q)
    b_a = edge_operator_bi(edge_list, p)
    b_b = edge_operator_bi(edge_list, q)
    a_ab = edge_operator_aij(edge_list, p, q)
    qubit_op = (-1j * 0.5 * h1_pq) * ((b_b & a_ab) + (a_ab & b_a))
    return qubit_op


## SW2018 eq 37
def _double_excitation(
    edge_list: List, p: int, q: int, r: int, s: int, h2_pqrs: float
):  # pylint: disable=invalid-name
    b_p = edge_operator_bi(edge_list, p)
    b_q = edge_operator_bi(edge_list, q)
    b_r = edge_operator_bi(edge_list, r)
    b_s = edge_operator_bi(edge_list, s)
    a_pq = edge_operator_aij(edge_list, p, q)
    a_rs = edge_operator_aij(edge_list, r, s)
    a_pq = -a_pq if q < p else a_pq
    a_rs = -a_rs if s < r else a_rs

    id_op = _pauli_id(edge_list.shape[1])
    qubit_op = (a_pq * a_rs) * (
        -id_op
        - b_p * b_q
        + b_p * b_r
        + b_p * b_s
        + b_q * b_r
        + b_q * b_s
        - b_r * b_s
        - b_p * b_q * b_r * b_s  ## !!! Why is this "-" ? Disagrees with SW2018, (GJL 2021)
    )
    final_coeff = 0.125
    qubit_op = (final_coeff * h2_pqrs) * qubit_op
    return qubit_op


def _number_excitation(
    edge_list: List, p: int, q: int, r: int, s: int, h2_pqrs: float
):  # pylint: disable=invalid-name
    b_p = edge_operator_bi(edge_list, p)
    b_q = edge_operator_bi(edge_list, q)
    id_op = _pauli_id(edge_list.shape[1])
    if p == r:
        b_s = edge_operator_bi(edge_list, s)
        a_qs = edge_operator_aij(edge_list, q, s)
        a_qs = -a_qs if s < q else a_qs
        qubit_op = (a_qs * b_s + b_q * a_qs) * (id_op - b_p)
        final_coeff = 1j * 0.25
    elif p == s:
        b_r = edge_operator_bi(edge_list, r)
        a_qr = edge_operator_aij(edge_list, q, r)
        a_qr = -a_qr if r < q else a_qr
        qubit_op = (a_qr * b_r + b_q * a_qr) * (id_op - b_p)
        final_coeff = 1j * -0.25
    elif q == r:
        b_s = edge_operator_bi(edge_list, s)
        a_ps = edge_operator_aij(edge_list, p, s)
        a_ps = -a_ps if s < p else a_ps
        qubit_op = (a_ps * b_s + b_p * a_ps) * (id_op - b_q)
        final_coeff = 1j * -0.25
    elif q == s:
        b_r = edge_operator_bi(edge_list, r)
        a_pr = edge_operator_aij(edge_list, p, r)
        a_pr = -a_pr if r < p else a_pr
        qubit_op = (a_pr * b_r + b_p * a_pr) * (id_op - b_q)
        final_coeff = 1j * 0.25
    else:
        raise ValueError("unexpected sequence of indices")
    qubit_op = (final_coeff * h2_pqrs) * qubit_op
    return qubit_op


def _analyze_term(term_str: str):
    """
    Return a string recording the type of interaction represented by `term_str` and
    a list of the factors and their indices in `term_str`.

    The types of interaction are 'number', 'excitation', 'coulomb_exchange', 'number_excitation',
    'double_excitation'.

    Args:
       `term_str`: a string of characters in `+-NI`.

    Returns:
       tuple: The first element is a string specifying the interaction type. See the method
       `_interaction_type`. The second is a list of factors as returned by `_unpack_term`.
    """
    (n_number, n_raise, n_lower), facs = _unpack_term(term_str, expand_number_op=True)
    ttype = _interaction_type(n_number, n_raise, n_lower)
    return ttype, facs


def _unpack_term(term_str: str, expand_number_op: bool = False):
    """
    Return a tuple specifying the counts of kinds of operators in `term_str` and
    a list of the factors and their indices in `term_str`.

    The factors are represented by tuples of the form `(i, c)`, where `i` is and index
    and `c` is a character.
    Allowed characters in `term_str` are 'N+-I`.
    The returned tuple contains counts for `N`, `+`, and `-`, in that order. Identity operators
    are ignored.

    Args:
       `term_str`: a string of characters in `+-NI`.
       `expand_number_op`: if `True`, number operators are expanded to `(i, '+')`, `(i, '-')`
         in the returned list of factors.

    Returns:
       tuple: A tuple of two elements. First, a tuple of three integers giving the number of
       number-, raising-, and -lowering operators. Second a list of factors represented by
       tuples of two elements: the first is an index and the second one of "-", "+", or "N".
       If `expand_number_op` is `True`, then factors of `N` are expanded.

    Raises:
       ValueError: if any character in `term_str` is not one of "+-IN".
    """
    (n_number, n_raise, n_lower) = (0, 0, 0)
    facs = []
    for i, c in enumerate(term_str):
        if c == "I":
            continue
        if c == "+":
            n_raise += 1
            facs.append((i, "+"))
        elif c == "-":
            n_lower += 1
            facs.append((i, "-"))
        elif c == "N":
            n_number += 1
            if expand_number_op:
                facs.append((i, "+"))
                facs.append((i, "-"))
            else:
                facs.append((i, "N"))
        else:
            raise ValueError("Unexpected operator ", c, " in term.")

    return (n_number, n_raise, n_lower), facs


def _interaction_type(n_number: int, n_raise: int, n_lower: int):
    """
    Return a string describing the type of interaction given the number of
    number, raising, and lowering operators.

    The types of interaction returned are 'number', 'excitation', 'coulomb_exchange',
    'number_excitation', 'double_excitation'.

    Args:
       `n_number`: the number of number operators
       `n_raise`: the number of raising operators
       `n_lower`: the number of lowering operators

    Returns:
      str: One of 'number', 'excitation', 'coulomb_exchange',
      'number_excitation', 'double_excitation'.

    Raises:
      ValueError: if the numbers of operators don't describe a one- or two-body term from
      an electronic Hamiltonian.
    """
    if n_raise == 0 and n_lower == 0:
        if n_number == 1:
            return "number"
        elif n_number == 2:
            return "coulomb_exchange"
        else:
            raise ValueError("unexpected number of number operators")
    elif n_raise == 1 and n_lower == 1:
        if n_number == 1:
            return "number_excitation"
        elif n_number == 0:
            return "excitation"
        else:
            raise ValueError("unexpected number of number operators")
    elif n_raise == 2 and n_lower == 2:
        return "double_excitation"
    else:
        raise ValueError("unexpected number of operators")


def number_of_modes(fer_op: FermionicOp):
    """Return the number of modes (including identities) in each term `fer_op`"""
    return len(fer_op.to_list()[0][0])


def operator_string(term: tuple):
    """
    Return the string describing the operators in the term extracted from a `FermionicOp`.
    given by `term.
    """
    return term[0]


def operator_coefficient(term: tuple):
    """
    Return the coefficient of the multi-mode operator term extracted from a `FermionicOp`.
    """
    return term[1]


## TODO: We may want a lower-triangular matrix. This may be the cause of the minus sign error.
def _get_adjacency_matrix(fer_op: FermionicOp):
    """
    Return an adjacency matrix specifying the edges in the BKSF graph for the
    operator `fer_op`.

    The graph is undirected, so we choose to return the edges in the upper triangle.
    (There are no self edges.). The lower triangle are all `False`.

    Returns:
          numpy.ndarray(dtype=bool): edge_matrix the adjacency matrix.
    """
    n_modes = number_of_modes(fer_op)
    edge_matrix = np.zeros((n_modes, n_modes), dtype=bool)
    for term in fer_op.to_list():
        _add_edges_for_term(edge_matrix, operator_string(term))
    return edge_matrix


def _add_one_edge(edge_matrix, i: int, j: int):
    """
    Add an edge from lesser index to greater. This maintains the upper triangular structure.
    """
    if i < j:
        edge_matrix[i, j] = True
    elif j < i:
        edge_matrix[j, i] = True
    else:
        raise ValueError("expecting i != j")


def _add_edges_for_term(edge_matrix, term_str: str):
    """
    Add one, two, or no edges to `edge_matrix` as dictated by the operator `term_str`.
    """
    (n_number, n_raise, n_lower), facs = _unpack_term(term_str)
    ttype = _interaction_type(n_number, n_raise, n_lower)
    # For 'excitation' and 'number_excitation', create and edge between the `+` and `-`.
    if ttype in ("excitation", "number_excitation"):
        inds = [i for (i, c) in facs if c in "+-"]
        if len(inds) != 2:
            raise ValueError("wrong number or raising and lowering")
        _add_one_edge(edge_matrix, *inds)
    # For `double_excitation` create an edge between the two `+`s and edge between the two `-`s.
    elif ttype == "double_excitation":
        raise_inds = [i for (i, c) in facs if c == "+"]
        lower_inds = [i for (i, c) in facs if c == "-"]
        _add_one_edge(edge_matrix, *raise_inds)
        _add_one_edge(edge_matrix, *lower_inds)


def bksf_edge_list_fermionic_op(fer_op_qn: FermionicOp):
    """
    Construct edge list required for the bksf algorithm.

    Args:
        fer_op_qn: the fermionic operator in the second quantized form

    Returns:
        numpy.ndarray: edge_list, a 2xE matrix, where E is total number of edge
                        and each pair denotes (from, to)
    """
    edge_matrix = _get_adjacency_matrix(fer_op_qn)
    edge_list_as_2d_array = np.asarray(np.nonzero(edge_matrix))
    return edge_list_as_2d_array


def edge_operator_aij(edge_list: List, i: int, j: int):
    """Calculate the edge operator A_ij.

    The definitions used here are consistent with arXiv:quant-ph/0003137

    Args:
        edge_list (numpy.ndarray): a 2xE matrix, where E is total number of edge
                                    and each pair denotes (from, to)
        i (int): specifying the edge operator A
        j (int): specifying the edge operator A

    Returns:
        Pauli: qubit operator
    """
    v = np.zeros(edge_list.shape[1])
    w = np.zeros(edge_list.shape[1])

    position_ij = -1
    qubit_position_i = np.asarray(np.where(edge_list == i))

    for edge_index in range(edge_list.shape[1]):
        if set((i, j)) == set(edge_list[:, edge_index]):
            position_ij = edge_index
            break

    w[position_ij] = 1

    for edge_index in range(qubit_position_i.shape[1]):
        i_i, j_j = qubit_position_i[:, edge_index]
        i_i = 1 if i_i == 0 else 0  # int(not(i_i))
        if edge_list[i_i][j_j] < j:
            v[j_j] = 1

    qubit_position_j = np.asarray(np.where(edge_list == j))
    for edge_index in range(qubit_position_j.shape[1]):
        i_i, j_j = qubit_position_j[:, edge_index]
        i_i = 1 if i_i == 0 else 0  # int(not(i_i))
        if edge_list[i_i][j_j] < i:
            v[j_j] = 1

    qubit_op = Pauli((v, w))
    return SparsePauliOp(qubit_op)


def edge_operator_bi(edge_list: List, i: int):
    """Calculate the edge operator B_i.

    The definitions used here are consistent with arXiv:quant-ph/0003137

    Args:
        edge_list (numpy.ndarray): a 2xE matrix, where E is total number of edge
                                    and each pair denotes (from, to)
        i (int): index for specifying the edge operator B.

    Returns:
        Pauli: qubit operator
    """
    qubit_position_matrix = np.asarray(np.where(edge_list == i))
    qubit_position = qubit_position_matrix[1]
    v = np.zeros(edge_list.shape[1])
    w = np.copy(v)
    v[qubit_position] = 1
    qubit_op = Pauli((v, w))
    return SparsePauliOp(qubit_op)


def _add_sparse_pauli(qubit_op1: SparsePauliOp, qubit_op2: SparsePauliOp):
    """
    Return `qubit_op1` and `qubit_op2`, except when either one is `None`.
    In the latter case, return the one that is not `None`. In other words, assume
    `None` signifies the additive identity.
    """
    if qubit_op1 is None:
        return qubit_op2
    elif qubit_op2 is None:
        return qubit_op1
    else:
        return qubit_op1 + qubit_op2


def _to_physicist_index_order(facs: List):
    """
    Reorder the factors `facs` to be two raising operators followed by two lowering operators and
    return the new factors and the phase incurred by the reordering. Note that `facs` are not in
    chemists' order, but rather sorted by index with least index first.

    Args:
      facs: a list of factors where each element is `(i, c)` where `i` is an integer index and
        `c` is either `-` or `+`.

    Returns:
        facs_out: A copy of the reordered factors or the input list (not a copy) if the factors are
          already in the desired order.
        phase: Either `1` or `-1`.

    Raises:
        ValueError: if `facs` does not represent a two-body interaction.
    """
    ops = [fac[1] for fac in facs]
    if ops == ["+", "+", "-", "-"]:
        facs_out = facs
        phase = 1
    elif ops == ["+", "-", "+", "-"]:
        facs_out = [facs[0], facs[2], facs[1], facs[3]]
        phase = -1
    elif ops == ["+", "-", "-", "+"]:
        facs_out = [facs[0], facs[3], facs[1], facs[2]]
        phase = 1
    else:
        raise ValueError("unexpected sequence of operators", facs)
    return facs_out, phase


class BravyiKitaevSFMapper(FermionicMapper):
    """The Bravyi-Kitaev super fast fermion-to-qubit mapping.

    Reference arXiv:1712.00446
    """

    def map(self, second_q_op: FermionicOp) -> PauliSumOp:
        if not isinstance(second_q_op, FermionicOp):
            raise TypeError("Type ", type(second_q_op), " not supported.")

        edge_list = bksf_edge_list_fermionic_op(second_q_op)
        sparse_pauli = _convert_operators(second_q_op, edge_list)

        ## Simplify and sort the result
        sparse_pauli = sparse_pauli.simplify()
        indices = sparse_pauli.table.argsort()
        table = sparse_pauli.table[indices]
        coeffs = sparse_pauli.coeffs[indices]
        sorted_sparse_pauli = SparsePauliOp(table, coeffs)

        return PauliSumOp(sorted_sparse_pauli)


def _convert_operators(fer_op_qn: FermionicOp, edge_list: List):
    fer_op_list = fer_op_qn.to_list()
    sparse_pauli = None
    for term in fer_op_list:
        term_type, facs = _analyze_term(operator_string(term))
        if facs[0][1] == "-":  # keep only one of h.c. pair
            continue
        ## Following only filters h.c. of some number-excitation op
        if facs[0][0] == facs[1][0]:  # first op is number op, which is it's own h.c.
            if len(facs) > 2 and facs[2][1] == "-":  # So, look at next op to skip h.c.
                continue

        if term_type == "number":  # a^\dagger_p a_p
            p = facs[0][0]  # pylint: disable=invalid-name
            h1_pq = operator_coefficient(term)
            sparse_pauli = _add_sparse_pauli(sparse_pauli, _number_operator(edge_list, p, h1_pq))
            continue

        if term_type == "excitation":
            (p, q) = [facs[i][0] for i in range(2)]  # p < q always   # pylint: disable=invalid-name
            h1_pq = operator_coefficient(term)
            sparse_pauli = _add_sparse_pauli(
                sparse_pauli, _excitation_operator(edge_list, p, q, h1_pq)
            )

        else:
            facs_reordered, phase = _to_physicist_index_order(facs)
            h2_pqrs = phase * operator_coefficient(term)
            (p, q, r, s) = [facs_reordered[i][0] for i in range(4)]  # pylint: disable=invalid-name
            if term_type == "double_excitation":
                sparse_pauli = _add_sparse_pauli(
                    sparse_pauli, _double_excitation(edge_list, p, q, r, s, h2_pqrs)
                )
            elif term_type == "coulomb_exchange":
                sparse_pauli = _add_sparse_pauli(
                    sparse_pauli, _coulomb_exchange(edge_list, p, q, s, h2_pqrs)
                )
            elif term_type == "number_excitation":
                # Note that h2_pqrs is not divided by 2 here, as in the aqua code
                sparse_pauli = _add_sparse_pauli(
                    sparse_pauli, _number_excitation(edge_list, p, q, r, s, h2_pqrs)
                )
            else:
                raise ValueError("Unknown interaction: ", term_type)

    return sparse_pauli
