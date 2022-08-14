import csv
from copy import deepcopy

from ortools.sat.python import cp_model
from pandas import DataFrame, concat


class OptimizerMLB:
    """Class containing methods and attributes related to building and running the
    constraint programming optimization model.
    """

    def __init__(
        self, hitters: DataFrame, pitchers: DataFrame, dummies: dict[DataFrame]
    ):
        """
        Parameters
        ----------
        hitters : DataFrame
            Hitters data after splitting in ``data_processing.hitter_pitcher_split``.
        pitchers : DataFrame
            Pitchers data after splitting in ``data_processing.hitter_pitcher_split``.
        dummies : dict of DataFrames
            Dictionary with dummy DataFrames for "hitter_name", "pitcher_opp",
            "pitcher_game", "hitter_game", and "hitter_team".
        """
        self.pitchers = pitchers.copy()
        self.hitters = hitters.copy()
        self.dummies = dummies.copy()

    def create_model(self):
        """Create the Constraint Programming model object and decision variables."""
        self.model = cp_model.CpModel()

        # List of decision variables for each position
        self.pitchers_var = [
            self.model.NewBoolVar(self.pitchers.iloc[i]["Name"])
            for i in range(len(self.pitchers))
        ]
        self.hitters_var = [
            self.model.NewBoolVar(self.hitters.iloc[i]["Name"])
            for i in range(len(self.hitters))
        ]

    def add_model_constraints(self):
        """Add constraints to ``self.model`` that are constant across all lineups."""
        # NUMBER PLAYERS constraint
        # Also doubles as an All Different constraint b/c 10 unique players
        # need to be selected
        self.model.Add(
            sum([self.pitchers_var[i] for i in range(len(self.pitchers_var))]) == 2
        )
        self.model.Add(
            sum([self.hitters_var[i] for i in range(len(self.hitters_var))]) == 8
        )

        # Make sure each player name is used only once - account for dual
        # position players
        for col in self.dummies["hitter_name"].columns:
            self.model.Add(
                sum(
                    [
                        self.hitters_var[i] * self.dummies["hitter_name"].loc[i, col]
                        for i in range(len(self.hitters_var))
                    ]
                )
                <= 1
            )
        # SALARY constraint
        self.model.Add(
            sum(
                [
                    self.pitchers_var[i] * self.pitchers.loc[i]["Salary"]
                    for i in range(len(self.pitchers_var))
                ]
            )
            + sum(
                [
                    self.hitters_var[i] * self.hitters.loc[i]["Salary"]
                    for i in range(len(self.hitters_var))
                ]
            )
            <= 50000
        )
        # POSITON constraints
        self.model.Add(
            sum(
                [
                    self.hitters_var[i] * self.hitters.loc[i]["C_bool"]
                    for i in range(len(self.hitters_var))
                ]
            )
            == 1
        )
        self.model.Add(
            sum(
                [
                    self.hitters_var[i] * self.hitters.loc[i]["1B_bool"]
                    for i in range(len(self.hitters_var))
                ]
            )
            == 1
        )
        self.model.Add(
            sum(
                [
                    self.hitters_var[i] * self.hitters.loc[i]["2B_bool"]
                    for i in range(len(self.hitters_var))
                ]
            )
            == 1
        )
        self.model.Add(
            sum(
                [
                    self.hitters_var[i] * self.hitters.loc[i]["3B_bool"]
                    for i in range(len(self.hitters_var))
                ]
            )
            == 1
        )
        self.model.Add(
            sum(
                [
                    self.hitters_var[i] * self.hitters.loc[i]["SS_bool"]
                    for i in range(len(self.hitters_var))
                ]
            )
            == 1
        )
        self.model.Add(
            sum(
                [
                    self.hitters_var[i] * self.hitters.loc[i]["OF_bool"]
                    for i in range(len(self.hitters_var))
                ]
            )
            == 3
        )
        # PITCHER NOT FACING HITTERS constraint
        for i in range(len(self.pitchers_var)):
            team = self.pitchers.loc[i, "team"]
            self.model.Add(
                8 * self.pitchers_var[i]
                + sum(
                    [
                        self.hitters_var[k] * self.dummies["pitcher_opp"].loc[k, team]
                        for k in range(len(self.hitters_var))
                    ]
                )
                <= 8
            )
        # PLAYERS FROM AT LEAST 2 GAMES constraint
        # sum pitcher and hitter from any game and has to be less than 9
        # 10 players in each game, meaning at most 9 can be selected
        # from a single game
        for game in self.dummies["pitcher_game"].columns:
            self.model.Add(
                sum(
                    [
                        self.pitchers_var[i] * self.dummies["pitcher_game"].loc[i, game]
                        for i in range(len(self.pitchers_var))
                    ]
                )
                + sum(
                    [
                        self.hitters_var[i] * self.dummies["hitter_game"].loc[i, game]
                        for i in range(len(self.hitters_var))
                    ]
                )
                <= 9
            )
        # NO MORE THAN 5 HITTERS FROM ONE TEAM constraint
        for team in self.dummies["hitter_team"].columns:
            self.model.Add(
                sum(
                    [
                        self.hitters_var[i] * self.dummies["hitter_team"].loc[i, team]
                        for i in range(len(self.hitters_var))
                    ]
                )
                <= 5
            )

    def create_lineup(
        self,
        binary_lineups_pitchers,
        binary_lineups_hitters,
        auto_stack=False,
        team_stack=None,
        stack_num=4,
        variance=0,
    ):
        """Create and runs optimization model.

        Returns tuple of two lists - (player_indexes_list, binary_lineup_list).
        The player index list is just a list with each of the 8 player indexes
        of the players selected by the optimizer. The binary lineup list is a
        list of 1s and 0s with a 1 indicating a player is in the lineup and 0
        being the player is not.

        Parameters
        ----------
        binary_lineups_pitchers : list
            List of binary pitcher lineups with 1s and 0s for players who are
            in or out of lineup. Used with 'variance' parameter to output
            unique lineups.
        binary_lineups_hitters : list
            Same as *binary_lineups_pitchers* but with list representing
            hitters.
        auto_stack : bool, default False
            If True, force lineup to include at least 4 players from same team.
            *team_stack* must be None if *auto_stack* is True.
        team_stack : str, default None
            Team abbreviation to stack at least *stack_num* number of
            players from. *auto_stack* must be False if this is not None.
        stack_num : int, default 4, must be between 0 and 5 (inclusive)
            Minimum number of players to be stacked from at least one team.
            Only applied if either *auto_stack* is True or *team_stack* is not
            None. If *auto_stack* is True, the team that is stacked will be
            selected by algotithm. If *team_stack* is specified, this will be
            the minimum number of players from the specified team to be included
            in the lineup.
        variance : int, default 0, Max=10, Min=0
            The min number of players that must be different in every lineup.
            Uses 'binary_lineups' parameter as list of already created lineups
            and creates constraint that each lineup must have 'variance'
            number of different players in each lineup. If parameter=0, every
            lineup would be the same as no players would need to be different
            from previous lineups. If parameter=10, then every lineup would
            have to be completely unique with no single player being the same
            in any lineup.
        """
        # Make sure lineups is list and variance is in
        assert isinstance(
            binary_lineups_pitchers, list
        ), "'binary_lineups_pitchers' type needs to be list"
        assert isinstance(
            binary_lineups_hitters, list
        ), "'binary_lineups_hitters' type needs to be list"
        assert isinstance(variance, int), "'variance' type needs to be int"
        assert variance >= 0 and variance <= 10, "'variance' must be ≥= 0 and <=10"
        assert (
            isinstance(team_stack, str) or team_stack is None
        ), "'team_stack' must be type string or None"
        assert not auto_stack or not team_stack, (
            "At least one of 'auto_stack' and 'team_stack' must be " "False/None."
        )
        assert stack_num >= 0 and stack_num <= 5, "'stack_num' must be >= 0 and <= 5"

        if not hasattr(self, "model"):
            self.create_model()
            self.add_model_constraints()
        # Start with copy of model with constant constraints and add flexible ones as
        # needed below based on function args
        model = deepcopy(self.model)

        ###################### ADD FLEXIBLE CONSTRAINTS ######################

        # VARIANCE constraint
        # constraint is the number of players in each new lineup that must
        # be different from lineups already created. Use 8-variance b/c
        # just using variance would be the number of same players allowed
        # in each lineup where lower=more variance and higher=lower variance
        # but want to have higher number = higher variance and lower =
        # less varianceS
        variance = 10 - variance

        # loops through each previous binary lineup ('binary_lineups' is list
        # of lists of 1s and 0s of previous lineups) and says that the sum
        # of the same players from lineup in 'binary_lineups' and 'players'
        # cannot be more than the variance parameter int
        # if variance parameter was 0 then no lineup would be different
        # because all 8 players could be the same, if it was 8 then no
        # lineup could have the same player
        for k in range(len(binary_lineups_pitchers)):
            model.Add(
                sum(
                    [
                        binary_lineups_pitchers[k][i] * self.pitchers_var[i]
                        for i in range(len(self.pitchers_var))
                    ]
                )
                + sum(
                    [
                        binary_lineups_hitters[k][i] * self.hitters_var[i]
                        for i in range(len(self.hitters_var))
                    ]
                )
                <= variance
            )

        # STACKING constraint - auto stack, no input on specific teams to stack
        # make each unique team a decision variable
        # sum(players from single team) >= (stack_num * team_stack_var)
        #
        # team_stack_var >= 1  # at least one stack
        # forces at least one team to have 4 players in lineup
        if auto_stack:
            teams = self.dummies["hitter_team"].columns
            team_stack_var = [model.NewBoolVar(teams[i]) for i in range(len(teams))]
            for t in range(len(teams)):
                model.Add(
                    sum(
                        [
                            self.hitters_var[i]
                            * self.dummies["hitter_team"].loc[i, teams[t]]
                            for i in range(len(self.hitters_var))
                        ]
                    )
                    >= stack_num * team_stack_var[t]
                )
            model.Add(sum([team_stack_var[i] for i in range(len(team_stack_var))]) >= 1)

        if team_stack:
            model.Add(
                sum(
                    [
                        self.hitters_var[i]
                        * self.dummies["hitter_team"].loc[i, team_stack]
                        for i in range(len(self.hitters_var))
                    ]
                )
                >= stack_num
            )

        ######################## SOLVE MODEL ########################

        model.Maximize(
            sum(
                [
                    self.pitchers_var[i] * self.pitchers.loc[i]["ppg_projection"]
                    for i in range(len(self.pitchers_var))
                ]
            )
            + sum(
                [
                    self.hitters_var[i] * self.hitters.loc[i]["ppg_projection"]
                    for i in range(len(self.hitters_var))
                ]
            )
        )

        solver = cp_model.CpSolver()
        status = solver.Solve(model)

        # if not optimal, print the status and return None
        if status == cp_model.OPTIMAL:
            pass
        elif status == cp_model.FEASIBLE:
            print("Feasible")
            return None
        elif status == cp_model.INFEASIBLE:
            print("Infeasible")
            return None
        elif status == cp_model.MODEL_INVALID:
            print("Model Invalid")
            return None

        ################### OUTPUT LIST OF PLAYER INDEXES ###################

        # create list to hold player indexes
        pitcher_indexes = []
        hitter_indexes = []

        # Also create binary list of 0 and 1 that is equal len as 'players'
        # decision variable list with 1 being player in lineup and 0 not
        binary_pitchers = []
        binary_hitters = []

        # loop through and append player indexes that solver has chosen and
        # also create binary list
        for j in range(len(self.pitchers_var)):
            if solver.Value(self.pitchers_var[j]) == 1:
                pitcher_indexes.append(self.pitchers.iloc[j]["index"])
                binary_pitchers.append(1)
            else:
                binary_pitchers.append(0)

        for j in range(len(self.hitters_var)):
            if solver.Value(self.hitters_var[j]) == 1:
                hitter_indexes.append(self.hitters.iloc[j]["index"])
                binary_hitters.append(1)
            else:
                binary_hitters.append(0)

        # player indexes used to more easily read data by linking back to df
        # binary lineups list used for variance metric
        return {
            "pitcher_indexes": pitcher_indexes,
            "hitter_indexes": hitter_indexes,
            "binary_pitchers": binary_pitchers,
            "binary_hitters": binary_hitters,
        }

    def run_lineups(
        self,
        num_lineups,
        auto_stack=False,
        team_stack=None,
        stack_num=4,
        variance=0,
        print_progress=False,
    ):
        """Create 'num_lineups' number of lineups using the self.create_lineup()
        method.

        Parameters
        ----------
        num_lineups : int
            Number of lineups to create.
        auto_stack : bool, default False
            If True, force lineup to include at least 4 players from same team.
            *team_stack* must be None if *auto_stack* is True.
        team_stack : str, default None
            Team abbreviation to stack at least *stack_num* number of
            players from. *auto_stack* must be False if this is not None.
        stack_num : int, default 4, must be between 0 and 5 (inclusive)
            If *team_stack* is not None, lineup must have at least this number
            of hitters from team *team_stack*. If this number is 0 then no
            players from *team_stack* will be included in lineup.
        variance : int, default 0, Max=10, Min=0
            The min number of players that must be different in every lineup.
            Uses 'binary_lineups' parameter as list of already created lineups
            and creates constraint that each lineup must have 'variance'
            number of different players in each lineup. If parameter=0, every
            lineup would be the same as no players would need to be different
            from previous lineups. If parameter=10, then every lineup would
            have to be completely unique with no single player being the same
            in any lineup.
        print_progress : bool, default False
            If True, print update after each lineup is created.

        Returns
        -------
        Creates attributes for 'pitcher_indexes', 'hitter_indexes',
        'binary_lineups_pitchers', 'binary_lineups_hitters' if not already
        created. If attributes already created function will create new lineups
        building upon those already created.
        """

        def print_num_lineup(num_lineups, i):
            if print_progress:
                print(i + 1, "/", num_lineups, sep=" ")
            else:
                pass

        # create empty lists that will end up as list of lists
        # will create empty lists if not already created
        if not hasattr(self, "pitcher_indexes"):
            self.pitcher_indexes = []
        if not hasattr(self, "hitter_indexes"):
            self.hitter_indexes = []
        if not hasattr(self, "binary_lineups_pitchers"):
            self.binary_lineups_pitchers = []
        if not hasattr(self, "binary_lineups_hitters"):
            self.binary_lineups_hitters = []

        ## Create lineups ##
        for i in range(num_lineups):
            lineup = self.create_lineup(
                self.binary_lineups_pitchers,
                self.binary_lineups_hitters,
                auto_stack=auto_stack,
                team_stack=team_stack,
                stack_num=stack_num,
                variance=variance,
            )

            self.pitcher_indexes.append(lineup["pitcher_indexes"])
            self.hitter_indexes.append(lineup["hitter_indexes"])
            self.binary_lineups_pitchers.append(lineup["binary_pitchers"])
            self.binary_lineups_hitters.append(lineup["binary_hitters"])

            print_num_lineup(num_lineups, i)

        print("COMPLETE")

    def csv_output(self, filename):
        """Output csv file of lineups using the self.pitcher_indexes and
        self.hitter_indexes attributes and can be uploaded to Draftkings site.

        Parameters
        ----------
        filename : str
            Name of output csv file.
        """
        assert len(self.pitcher_indexes) == len(self.hitter_indexes), (
            "length of pitcher_indexes and hitter_indexes attributes must be " "equal."
        )
        assert (
            type(self.pitcher_indexes) == list
        ), "pitcher_indexes attribute must be list."
        assert (
            type(self.hitter_indexes) == list
        ), "hitter_indexes attribute must be list."

        uploadable_lineups = [["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]]
        cols = ["Name + ID", "Position"]

        for i in range(len(self.pitcher_indexes)):

            lineup_df = concat(
                [
                    self.pitchers.loc[self.pitcher_indexes[i], cols],
                    self.hitters.loc[self.hitter_indexes[i], cols],
                ]
            )

            # single lineup list
            lineup_list = []

            lineup_list.extend(
                lineup_df[lineup_df["Position"].str.contains("P")]["Name + ID"].values
            )
            lineup_list.extend(
                lineup_df[lineup_df["Position"] == "C"]["Name + ID"].values
            )
            lineup_list.extend(
                lineup_df[lineup_df["Position"] == "1B"]["Name + ID"].values
            )
            lineup_list.extend(
                lineup_df[lineup_df["Position"] == "2B"]["Name + ID"].values
            )
            lineup_list.extend(
                lineup_df[lineup_df["Position"] == "3B"]["Name + ID"].values
            )
            lineup_list.extend(
                lineup_df[lineup_df["Position"] == "SS"]["Name + ID"].values
            )
            lineup_list.extend(
                lineup_df[lineup_df["Position"] == "OF"]["Name + ID"].values
            )

            uploadable_lineups.append(lineup_list)

        with open(filename, "w") as csvFile:
            writer = csv.writer(csvFile)
            writer.writerows(uploadable_lineups)

            csvFile.close()

        return "Complete"
