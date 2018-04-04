"""
Tax-Calculator abstract base parameters class.
"""
# CODING-STYLE CHECKS:
# pep8 parameters.py

import os
import json
import six
import abc
import ast
import collections as collect
import numpy as np
from taxcalc.utils import read_egg_json


class ParametersBase(object):
    """
    Inherit from this class for Policy, Behavior, Consumption, Growdiff, and
    other groups of parameters that need to have a set_year method.
    Override this __init__ method and DEFAULTS_FILENAME.
    """
    __metaclass__ = abc.ABCMeta

    DEFAULTS_FILENAME = None

    @classmethod
    def default_data(cls, metadata=False, start_year=None):
        """
        Return parameter data read from the subclass's json file.

        Parameters
        ----------
        metadata: boolean

        start_year: int or None

        Returns
        -------
        params: dictionary of data
        """
        # extract different data from DEFAULT_FILENAME depending on start_year
        if start_year is None:
            params = cls._params_dict_from_json_file()
        else:
            ppo = cls(start_year)
            ppo.set_year(start_year)
            params = getattr(ppo, '_vals')
            params = ParametersBase._revised_default_data(params, start_year,
                                                          nyrs, ppo)
        # return different data from params dict depending on metadata value
        if metadata:
            return params
        else:
            return {name: data['value'] for name, data in params.items()}

    def __init__(self):
        pass

    def initialize(self, start_year, num_years):
        """
        Called from subclass __init__ function.
        """
        self._current_year = start_year
        self._start_year = start_year
        self._num_years = num_years
        self._end_year = start_year + num_years - 1
        self.set_default_vals()

    def set_default_vals(self, known_years=999999):
        """
        Called by initialize method and from some subclass methods.
        """
        if hasattr(self, '_vals'):
            for name, data in self._vals.items():
                if not isinstance(name, six.string_types):
                    msg = 'parameter name {} is not a string'
                    raise ValueError(msg.format(name))
                integer_values = data.get('integer_value', None)
                values = data.get('value', None)
                if values:
                    # removed parameter extension from start year to end of
                    # budget window. Currently this stores the default value
                    # as a list object of length 1
                    setattr(self, name,
                            self._expand_array(values, integer_values))

        self.set_year(self._start_year)

    @property
    def num_years(self):
        """
        ParametersBase class number of parameter years property.
        """
        return self._num_years

    @property
    def current_year(self):
        """
        ParametersBase class current calendar year property.
        """
        return self._current_year

    @property
    def start_year(self):
        """
        ParametersBase class first parameter year property.
        """
        return self._start_year

    @property
    def end_year(self):
        """
        ParametersBase class lasst parameter year property.
        """
        return self._end_year

    def set_year(self, year):
        """
        Set parameters to their values for the specified calendar year.

        Parameters
        ----------
        year: int
            calendar year for which to current_year and parameter values

        Raises
        ------
        ValueError:
            if year is not in [start_year, end_year] range.

        Returns
        -------
        nothing: void

        Notes
        -----
        To increment the current year, use the following statement::

            behavior.set_year(behavior.current_year + 1)

        where, in this example, behavior is a Behavior object.
        """
        if year < self.start_year or year > self.end_year:
            msg = 'year {} passed to set_year() must be in [{},{}] range.'
            raise ValueError(msg.format(year, self.start_year, self.end_year))
        self._current_year = year
        year_zero_indexed = 0 # assume everything goes into effect immediately
        if hasattr(self, '_vals'):
            for name in self._vals:
                if isinstance(name, six.string_types):
                    arr = getattr(self, name)
                    setattr(self, name[1:], arr[year_zero_indexed])

    # ----- begin private methods of ParametersBase class -----

    @staticmethod
    def _revised_default_data(params, start_year, nyrs, ppo):
        """
        Return revised default parameter data.

        Parameters
        ----------
        params: dictionary of NAME:DATA pairs for each parameter
            as defined in calling default_data staticmethod.

        start_year: int
            as defined in calling default_data staticmethod.

        nyrs: int
            as defined in calling default_data staticmethod.

        ppo: Policy object
            as defined in calling default_data staticmethod.

        Returns
        -------
        params: dictionary of revised parameter data

        Notes
        -----
        This staticmethod is called from default_data staticmethod in
        order to reduce the complexity of the default_data staticmethod.
        """
        start_year_str = '{}'.format(start_year)
        for name, data in params.items():
            data['start_year'] = start_year
            values = data['value']
            num_values = len(values)
            if num_values <= nyrs:
                # val should be the single start_year value
                rawval = getattr(ppo, name[1:])
                if isinstance(rawval, np.ndarray):
                    val = rawval.tolist()
                else:
                    val = rawval
                data['value'] = [val]
                data['row_label'] = [start_year_str]
            else:  # if num_values > nyrs
                # val should extend beyond the start_year value
                data['value'] = data['value'][(nyrs - 1):]
                data['row_label'] = data['row_label'][(nyrs - 1):]
        return params

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

    def _update(self, year_mods):
        """
        Private method used by public implement_reform and update_* methods
        in inheriting classes.

        Parameters
        ----------
        year_mods: dictionary containing a single YEAR:MODS pair
            see Notes below for details on dictionary structure.

        Raises
        ------
        ValueError:
            if year_mods is not a dictionary of the expected structure.

        Returns
        -------
        nothing: void

        Notes
        -----
        This is a private method that should **never** be used by clients
        of the inheriting classes.  Instead, always use the public
        implement_reform or update_behavior methods.
        This is a private method that helps the public methods work.

        This method implements a policy reform or behavior modification,
        the provisions of which are specified in the year_mods dictionary,
        that changes the values of some policy parameters in objects of
        inheriting classes.  This year_mods dictionary contains exactly one
        YEAR:MODS pair, where the integer YEAR key indicates the
        calendar year for which the reform provisions in the MODS
        dictionary are implemented.  The MODS dictionary contains
        PARAM:VALUE pairs in which the PARAM is a string specifying
        the policy parameter (as used in the DEFAULTS_FILENAME default
        parameter file) and the VALUE is a Python list of post-reform
        values for that PARAM in that YEAR.  Beginning in the year
        following the implementation of a reform provision, the
        parameter whose value has been changed by the reform continues
        to be inflation indexed, if relevant, or not be inflation indexed
        according to that parameter's cpi_inflated value loaded from
        DEFAULTS_FILENAME.  For a cpi-related parameter, a reform can change
        the indexing status of a parameter by including in the MODS dictionary
        a term that is a PARAM_cpi:BOOLEAN pair specifying the post-reform
        indexing status of the parameter.

        So, for example, to raise the OASDI (i.e., Old-Age, Survivors,
        and Disability Insurance) maximum taxable earnings beginning
        in 2018 to $500,000 and to continue indexing it in subsequent
        years as in current-law policy, the YEAR:MODS dictionary would
        be as follows::

            {2018: {"_SS_Earnings_c":[500000]}}

        But to raise the maximum taxable earnings in 2018 to $500,000
        without any indexing in subsequent years, the YEAR:MODS
        dictionary would be as follows::

            {2018: {"_SS_Earnings_c":[500000], "_SS_Earnings_c_cpi":False}}

        And to raise in 2019 the starting AGI for EITC phaseout for
        married filing jointly filing status (which is a two-dimensional
        policy parameter that varies by the number of children from zero
        to three or more and is inflation indexed), the YEAR:MODS dictionary
        would be as follows::

            {2019: {"_EITC_ps_MarriedJ":[[8000, 8500, 9000, 9500]]}}

        """
        # check YEAR value in the single YEAR:MODS dictionary parameter
        if not isinstance(year_mods, dict):
            msg = 'year_mods is not a dictionary'
            raise ValueError(msg)
        if len(year_mods.keys()) != 1:
            msg = 'year_mods dictionary must contain a single YEAR:MODS pair'
            raise ValueError(msg)
        year = list(year_mods.keys())[0]
        if year != self.current_year:
            msg = 'YEAR={} in year_mods is not equal to current_year={}'
            raise ValueError(msg.format(year, self.current_year))
        # check that MODS is a dictionary
        if not isinstance(year_mods[year], dict):
            msg = 'mods in year_mods is not a dictionary'
            raise ValueError(msg)
        # implement reform provisions included in the single YEAR:MODS pair
        num_years_to_expand = (self.start_year + self.num_years) - year
        all_names = set(year_mods[year].keys())  # no duplicate keys in a dict
        used_names = set()  # set of used parameter names in MODS dict
        for name, values in year_mods[year].items():
            if name in self._vals:
                integer_values = self._vals[name].get('integer_value')
            else:
                msg = 'parameter name {} not in parameter values dictionary'
                raise ValueError(msg.format(name))
            # set post-reform values of parameter with name
            used_names.add(name)
            cval = getattr(self, name, None)
            nval = self._expand_array(values, integer_values)
            cval[(year - self.start_year):] = nval
        # handle unused parameter names, all of which end in _cpi, but some
        # parameter names ending in _cpi were handled above
        unused_names = all_names - used_names
        for name in unused_names:
            used_names.add(name)
            pname = name[:-4]  # root parameter name
            if pname not in self._vals:
                msg = 'root parameter name {} not in values dictionary'
                raise ValueError(msg.format(pname))
            pindexed = year_mods[year][name]
            self._vals[pname]['cpi_inflated'] = pindexed  # remember status
            cval = getattr(self, pname, None)
            pvalues = [cval[year - self.start_year]]
            integer_values = self._vals[pname]['integer_value']
            nval = self._expand_array(pvalues, integer_values)
            cval[(year - self.start_year):] = nval
        # confirm that all names have been used
        assert len(used_names) == len(all_names)
        # implement updated parameters for year
        self.set_year(year)

    @staticmethod
    def _expand_array(x, x_dtype_int):
        """
        Converts object into numpy array if object is of type list
        """
        if not isinstance(x, list) and not isinstance(x, np.ndarray):
            msg = '_expand_array expects x to be a list or numpy array'
            raise ValueError(msg)
        if isinstance(x, list):
            if x_dtype_int:
                x = np.array(x, np.int8)
            else:
                x = np.array(x, np.float64)
        return x


    OP_DICT = {
        '+': lambda pvalue, val: pvalue + val,
        '-': lambda pvalue, val: pvalue - val,
        '*': lambda pvalue, val: pvalue * val,
        '/': lambda pvalue, val: pvalue / val if val > 0 else 'ERROR: Cannot divide by zero',
    }

    def simple_eval(self, param_string):
        """
        Parses `param_string` and returns result. `param_string can be either:
            1. `param_name op scalar` -- this will be parsed into param, op, and scalar
                    where `op` is a key in `OP_DICT`. The corresponding function is
                    applied to the parameter value and the scalar value.

            2. `param_name` -- simply return the parameter value that is retrieved
                    from the object

        returns: float used for validation
        """
        pieces = param_string.split(' ')
        validate_against = pieces[0]
        # param_string is of the form 'param_name op scalar'
        if len(pieces) > 1:
            op = pieces[1]
            # parse string to python type (i.e. str --> int, float, bool)
            scalar = ast.literal_eval(pieces[2])
            value_against = getattr(self, validate_against)
            assert value_against is not None and isinstance(value_against, (int, float, np.ndarray))
            assert op in ParametersBase.OP_DICT
            return ParametersBase.OP_DICT[op](value_against, scalar)
        else:
            # vval is just the parameter name
            return getattr(self, param_string)
