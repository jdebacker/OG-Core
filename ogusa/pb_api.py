import json
import os
import collections as collect
import six
import numpy as np

from taxcalc.growfactors import Growfactors
from taxcalc.policy import Policy

import ogusa
from ogusa.parametersbase import ParametersBase


class Specifications(ParametersBase):
    DEFAULTS_FILENAME = 'default_parameters.json'
    LAST_BUDGET_YEAR = 2027  # increases by one every calendar year

    def __init__(self,
                 start_year,
                 num_years=None,
                 initial_estimates=False):
        super(Specifications, self).__init__()

        if num_years is None:
            num_years = Specifications.LAST_BUDGET_YEAR - start_year
        # reads in default data
        self._vals = self._params_dict_from_json_file()

        if num_years < 1:
            raise ValueError('num_years cannot be less than one')

        # does cheap calculations such as growth
        self.initialize(start_year, num_years, initial_estimates=False)

        self.warnings = ''
        self.errors = ''
        self._ignore_errors = False

    def initialize(self, start_year, num_years, initial_estimates=False):
        """
        ParametersBase reads JSON file and sets attributes to self
        Next call self.ogusa_set_default_vals for further initialization
        If estimate_params is true, then run long running estimation routines
        """
        super(Specifications, self).initialize(start_year, num_years)
        self.ogusa_set_default_vals()
        if initial_estimates:
            self.estimate_parameters()

    def ogusa_set_default_vals(self):
        """
        Does cheap calculations such as calculating/applying growth rates
        """
        self.b_ellipse, self.upsilon = ogusa.elliptical_u_est.estimation(
            self.frisch[0],
            self.ltilde[0]
        )
        # call some more functions

    def esitimate_parameters(self, data=None, reform={}):
        """
        Runs long running parameter estimatation routines such as estimating
        tax function parameters
        """
        # self.tax_func_estimate = tax_func_estimate(self.BW, self.S, self.starting_age, self.ending_age,
        #                                 self.start_year, self.baseline,
        #                                 self.analytical_mtrs, self.age_specific,
        #                                 reform=None, data=data)
        pass

    def default_specs(self):
        """
        Return Policy object same as self except with current-law policy.
        """
        startyear = self.start_year
        defaults = Specifications(start_year=startyear, num_years=self.num_years)
        defaults.set_year(self.current_year)
        return defaults

    def update_specifications(self, reform):
        # check that all reform dictionary keys are integers
        # check that all reform dictionary keys are integers
        if not isinstance(reform, dict):
            raise ValueError('ERROR: YYYY PARAM reform is not a dictionary')
        if not reform:
            return  # no reform to implement
        reform_years = sorted(list(reform.keys()))
        for year in reform_years:
            if not isinstance(year, int):
                msg = 'ERROR: {} KEY {}'
                details = 'KEY in reform is not an integer calendar year'
                raise ValueError(msg.format(year, details))
        # check range of remaining reform_years
        first_reform_year = min(reform_years)
        if first_reform_year < self.start_year:
            msg = 'ERROR: {} YEAR reform provision in YEAR < start_year={}'
            raise ValueError(msg.format(first_reform_year, self.start_year))
        if first_reform_year < self.current_year:
            msg = 'ERROR: {} YEAR reform provision in YEAR < current_year={}'
            raise ValueError(msg.format(first_reform_year, self.current_year))
        last_reform_year = max(reform_years)
        if last_reform_year > self.end_year:
            msg = 'ERROR: {} YEAR reform provision in YEAR > end_year={}'
            raise ValueError(msg.format(last_reform_year, self.end_year))
        # validate reform parameter names and types
        self._validate_parameter_names_types(reform)
        if not self._ignore_errors and self.errors:
            raise ValueError(self.errors)
        # implement the reform year by year
        precall_current_year = self.current_year
        reform_parameters = set()
        for year in reform_years:
            self.set_year(year)
            reform_parameters.update(reform[year].keys())
            self._update({year: reform[year]})
        self.set_year(precall_current_year)
        # validate reform parameter values
        self._validate_parameter_values(reform_parameters)

    def read_json_parameters_object(self, parameters):
        raise NotImplementedError()

    def _validate_parameter_names_types(self, reform):
        """
        Skinny version of taxcalc.Policy._validate_parameter_values
        """
        # pylint: disable=too-many-branches,too-many-nested-blocks
        data_names = set(self._vals.keys())
        for year in sorted(reform.keys()):
            for name in reform[year]:
                if name not in data_names:
                    msg = '{} {} unknown parameter name'
                    self.errors += (
                        'ERROR: ' + msg.format(year, name) + '\n'
                    )
                else:
                    # check parameter value type
                    bool_type = self._vals[name]['boolean_value']
                    int_type = self._vals[name]['integer_value']
                    assert isinstance(reform[year][name], list)
                    pvalue = reform[year][name][0]
                    if isinstance(pvalue, list):
                        scalar = False  # parameter value is a list
                    else:
                        scalar = True  # parameter value is a scalar
                        pvalue = [pvalue]  # make scalar a single-item list
                    for idx in range(0, len(pvalue)):
                        if scalar:
                            pname = name
                        else:
                            pname = '{}_{}'.format(name, idx)
                        pvalue_boolean = (
                            isinstance(pvalue[idx], bool) or
                            (isinstance(pvalue[idx], int) and
                                (pvalue[idx] == 0 or pvalue[idx] == 1)) or
                            (isinstance(pvalue[idx], float) and
                                (pvalue[idx] == 0.0 or pvalue[idx] == 1.0))
                        )
                        if bool_type:
                            if not pvalue_boolean:
                                msg = '{} {} value {} is not boolean'
                                self.errors += (
                                    'ERROR: ' +
                                    msg.format(year, pname, pvalue[idx]) +
                                    '\n'
                                )
                        elif int_type:
                            if not isinstance(pvalue[idx], int):
                                msg = '{} {} value {} is not integer'
                                self.errors += (
                                    'ERROR: ' +
                                    msg.format(year, pname, pvalue[idx]) +
                                    '\n'
                                )
                        else:  # param is neither bool_type nor int_type
                            if not isinstance(pvalue[idx], (float, int)):
                                msg = '{} {} value {} is not a number'
                                self.errors += (
                                    'ERROR: ' +
                                    msg.format(year, pname, pvalue[idx]) +
                                    '\n'
                                )


    def _validate_parameter_values(self, parameters_set):
        """
        Check values of parameters in specified parameter_set using
        range information from the current_law_policy.json file.
        """
        # pylint: disable=too-many-locals
        # pylint: disable=too-many-branches
        # pylint: disable=too-many-nested-blocks
        rounding_error = 100.0
        # above handles non-rounding of inflation-indexed parameter values
        clp = self.default_specs()
        parameters = sorted(parameters_set)
        syr = Specifications.JSON_START_YEAR
        for pname in parameters:
            pvalue = getattr(self, pname)
            for vop, vval in self._vals[pname]['range'].items():
                if isinstance(vval, six.string_types):
                    if vval == 'default':
                        vvalue = getattr(clp, pname)
                        if vop == 'min':
                            vvalue -= rounding_error
                        # the follow branch can never be reached, so it
                        # is commented out because it can never be tested
                        # (see test_range_infomation in test_policy.py)
                        # --> elif vop == 'max':
                        # -->    vvalue += rounding_error
                    else:
                        print(pname, vop, vval)
                        vvalue = self.simple_eval(vval)
                else:
                    vvalue = np.full(pvalue.shape, vval)
                assert pvalue.shape == vvalue.shape
                assert len(pvalue.shape) <= 2
                if len(pvalue.shape) == 2:
                    scalar = False  # parameter value is a list
                else:
                    scalar = True  # parameter value is a scalar
                for idx in np.ndindex(pvalue.shape):
                    out_of_range = False
                    if vop == 'min' and pvalue[idx] < vvalue[idx]:
                        out_of_range = True
                        msg = '{} {} value {} < min value {}'
                        extra = self._vals[pname]['out_of_range_minmsg']
                        if extra:
                            msg += ' {}'.format(extra)
                    if vop == 'max' and pvalue[idx] > vvalue[idx]:
                        out_of_range = True
                        msg = '{} {} value {} > max value {}'
                        extra = self._vals[pname]['out_of_range_maxmsg']
                        if extra:
                            msg += ' {}'.format(extra)
                    if out_of_range:
                        action = self._vals[pname]['out_of_range_action']
                        if scalar:
                            name = pname
                        else:
                            name = '{}_{}'.format(pname, idx[1])
                            if extra:
                                msg += '_{}'.format(idx[1])
                        if action == 'warn':
                            self.warnings += (
                                'WARNING: ' + msg.format(idx[0] + syr, name,
                                                         pvalue[idx],
                                                         vvalue[idx]) + '\n'
                            )
                        if action == 'stop':
                            self.errors += (
                                'ERROR: ' + msg.format(idx[0] + syr, name,
                                                       pvalue[idx],
                                                       vvalue[idx]) + '\n'
                            )


# copied from taxcalc.tbi.tbi.reform_errors_warnings--probably needs further
# changes
def reform_warnings_errors(user_mods):
    """
    The reform_warnings_errors function assumes user_mods is a dictionary
    returned by the Calculator.read_json_param_objects() function.

    This function returns a dictionary containing two STR:STR pairs:
    {'warnings': '<empty-or-message(s)>', 'errors': '<empty-or-message(s)>'}
    In each pair the second string is empty if there are no messages.
    Any returned messages are generated using current_law_policy.json
    information on known policy parameter names and parameter value ranges.

    Note that this function will return one or more error messages if
    the user_mods['policy'] dictionary contains any unknown policy
    parameter names or if any *_cpi parameters have values other than
    True or False.  These situations prevent implementing the policy
    reform specified in user_mods, and therefore, no range-related
    warnings or errors will be returned in this case.
    """
    rtn_dict = {'warnings': '', 'errors': ''}

    # create Policy object and implement reform
    pol = Policy()
    try:
        pol.update_specifications(user_mods['policy'])
        rtn_dict['warnings'] = pol.reform_warnings
        rtn_dict['errors'] = pol.reform_errors
    except ValueError as valerr_msg:
        rtn_dict['errors'] = valerr_msg.__str__()
    return rtn_dict

if __name__ == '__main__':
    specs = Specifications(2017)
    reform = {
        2017: {
            "tG1": [50],
            "T": [80]
        }
    }
    specs.update_specifications(reform)
    print('errors', specs.reform_errors)
    print('warnings', specs.reform_warnings)
