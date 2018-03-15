import json
import os
import collections as collect

from taxcalc.parameters import ParametersBase
from taxcalc.growfactors import Growfactors
from taxcalc.policy import Policy

class ParametersBaseOGUSA(ParametersBase):
    """
    Quick fix so that the path pulled from __file__ is relative to this file
    and not the `ParametersBase` file located int he conda installation path

    This allows us to read the `ogusa/default_parameters.json` file
    """

    @classmethod
    def _params_dict_from_json_file(cls):
        """
        Read DEFAULTS_FILENAME file and return complete dictionary.

        Parameters
        ----------
        nothing: void

        Returns
        -------
        params: dictionary
            containing complete contents of DEFAULTS_FILENAME file.
        """
        if cls.DEFAULTS_FILENAME is None:
            msg = 'DEFAULTS_FILENAME must be overridden by inheriting class'
            raise NotImplementedError(msg)
        path = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                            cls.DEFAULTS_FILENAME)
        if os.path.exists(path):
            with open(path) as pfile:
                params_dict = json.load(pfile,
                                        object_pairs_hook=collect.OrderedDict)
        else:
            # cannot call read_egg_ function in unit tests
            params_dict = read_egg_json(
                cls.DEFAULTS_FILENAME)  # pragma: no cover
        return params_dict

class Specs(ParametersBaseOGUSA):
    DEFAULTS_FILENAME = 'default_parameters.json'
    JSON_START_YEAR = 2013  # remains the same unless earlier data added
    LAST_KNOWN_YEAR = 2017  # last year for which indexed param vals are known
    LAST_BUDGET_YEAR = 2027  # increases by one every calendar year
    DEFAULT_NUM_YEARS = LAST_BUDGET_YEAR - JSON_START_YEAR + 1

    def __init__(self,
                 start_year=JSON_START_YEAR,
                 num_years=DEFAULT_NUM_YEARS,
                 initial_estimates=False):
        super(Specs, self).__init__()

        # reads in default data
        self._vals = self._params_dict_from_json_file()

        if num_years < 1:
            raise ValueError('num_years cannot be less than one')

        # does cheap calculations such as growth
        self.initialize(initial_estimates=False)

        self.reform_warnings = ''
        self.reform_errors = ''
        self._ignore_errors = False

    def initialize(self, initial_estimates=False):
        """
        ParametersBase reads JSON file and sets attributes to self
        Next call self.ogusa_set_default_vals for further initialization
        If estimate_params is true, then run long running estimation routines
        """
        super(Specs, self).initialize()
        self.ogusa_set_default_vals()
        if initial_estimates:
            self.estimate_parameters()

    def ogusa_set_default_vals(self):
        """
        Does cheap calculations such as calculating/applying growth rates
        """
        raise NotImplementedError()

    def esitimate_parameters(self):
        """
        Runs long running parameter estimatation routines such as estimating
        tax function parameters
        """
        raise NotImplementedError()

    def implement_reform(self, specs):
        """
        Follows Policy.implement_reform

        This is INCOMPLETE and needs to be filled in. This is the place
        to call parameter validating functions
        """

        self._validate_parameter_names_types(specs)
        if not self._ignore_errors and self.reform_errors:
            raise ValueError(self.reform_errors)

        self._validate_parameter_values(reform_parameters)

        raise NotImplementedError()

    def read_json_parameters_object(self, parameters):
        raise NotImplementedError()

    def _validate_parameter_names_types(self, reform):
        """
        hopefully can use taxcalc.Policy._validate_parameter_values here
        """
        raise NotImplementedError()

    def _validate_parameter_values(self, parameters_set):
        """
        hopefully can use taxcalc.Policy._validate_parameter_values here
        """
        raise NotImplementedError()


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
        pol.implement_reform(user_mods['policy'])
        rtn_dict['warnings'] = pol.reform_warnings
        rtn_dict['errors'] = pol.reform_errors
    except ValueError as valerr_msg:
        rtn_dict['errors'] = valerr_msg.__str__()
    return rtn_dict

if __name__ == '__main__':
    specs = Specs()
