# This code is part of Qiskit.
#
# (C) Copyright IBM 2022.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Utility functions to detect and transform the index-ordering convention of two-body integrals"""

import numpy

## These are the permutation symmetries satisfied by
## a rank-4 tensor of real two-body integrals in chemists'
## index order.
## HJO is Molecular Electronic Structure Theory by Helgaker, Jørgensen, Olsen
CHEM_INDEX_PERMUTATIONS = [
    "pqrs->qprs",  # (1.4.38) HJO (1)
    "pqrs->pqsr",  # (1.4.38) HJO (2)
    "pqrs->qpsr",  # (1.4.38) HJO (3)
    "pqrs->rspq",  # (1.4.17) HJO (4)
    "pqrs->rsqp",  # 1 and 4
    "pqrs->srpq",  # 2 and 4
    "pqrs->srqp",  # 3 and 4
]


def phys_to_chem(two_body_tensor):
    """
    Convert the rank-four tensor `two_body_tensor` representing two-body integrals from physicists'
    index order to chemists' index order: i,j,k,l -> i,l,j,k

    See `chem_to_phys`, `check_two_body_symmetries`.
    """
    permuted_tensor = numpy.einsum("ijkl->iljk", two_body_tensor)
    return permuted_tensor


def chem_to_phys(two_body_tensor):
    """
    Convert the rank-four tensor `two_body_tensor` representing two-body integrals from chemists'
    index order to physicists' index order: i,j,k,l -> i,k,l,j

    See `phys_to_chem`, `check_two_body_symmetries`.

    Note:
    Denote `chem_to_phys` by `g` and `phys_to_chem` by `h`. The elements `g`, `h`, `I` form
    a group with `gh = hg = I`, `g^2=h`, and `h^2=g`.
    """
    permuted_tensor = numpy.einsum("ijkl->iklj", two_body_tensor)
    return permuted_tensor


def _check_two_body_symmetry(tensor, test_number):
    """
    Return `True` if `tensor` passes symmetry test number `test_number`. Otherwise,
    return `False`.
    """
    permuted_tensor = numpy.einsum(CHEM_INDEX_PERMUTATIONS[test_number], tensor)
    return numpy.allclose(tensor, permuted_tensor)


def _check_two_body_symmetries(two_body_tensor, chemist=True):
    """
    Return `True` if the rank-4 tensor `two_body_tensor` has the required symmetries for coefficents
    of the two-electron terms.  If `chemist` is `True`, assume the input is in chemists' order,
    otherwise in physicists' order.

    If `two_body_tensor` is a correct tensor of indices, with the correct index order, it must pass the
    tests. If `two_body_tensor` is a correct tensor of indicies, but the flag `chemist` is incorrect,
    it will fail the tests, unless the tensor has accidental symmetries.
    This test may be used with care to discriminiate between the orderings.

    References: HJO Molecular Electronic-Structure Theory (1.4.17), (1.4.38)

    See `phys_to_chem`, `chem_to_phys`.
    """
    if not chemist:
        two_body_tensor = phys_to_chem(two_body_tensor)
    for test_number in range(len(CHEM_INDEX_PERMUTATIONS)):
        if not _check_two_body_symmetry(two_body_tensor, test_number):
            return False
    return True


def find_index_order(two_body_tensor):
    """
    Return the index-order convention of rank-four `two_body_tensor`.

    The index convention is determined by checking symmetries of the tensor.
    If the indexing convention can be determined, then one of `:chemist`,
    `:physicist`, or `:intermediate` is returned. The `:intermediate` indexing
    may be obtained by applying `chem_to_phys` to the physicists' convention or
    `phys_to_chem` to the chemists' convention. If the tests for each of these
    conventions fail, then `:unknown` is returned.

    See also: `chem_to_phys`, `phys_to_chem`.

    Note:
    The first of `:chemist`, `:physicist`, and `:intermediate`, in that order, to pass the tests
    is returned. If `two_body_tensor` has accidental symmetries, it may in fact satisfy more
    than one set of symmetry tests. For example, if all elements have the same value, then the
    symmetries for all three index orders are satisfied.
    """
    if _check_two_body_symmetries(two_body_tensor):
        return "chemist"
    permuted_tensor = phys_to_chem(two_body_tensor)
    if _check_two_body_symmetries(permuted_tensor):
        return "physicist"
    permuted_tensor = phys_to_chem(permuted_tensor)
    if _check_two_body_symmetries(permuted_tensor):
        return "intermediate"
    else:
        return "unknown"
