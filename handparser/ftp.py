import re
from datetime import datetime
from decimal import Decimal
from collections import OrderedDict
from handparser.common import PokerHand, ET, UTC, GAMES


class FullTiltHand(PokerHand):
    """Parses Full Tilt Poker hands the same way as PokerStarsHand class.

    PokerStars and Full Tilt hand histories are very similar, so parsing them is almost identical.
    There are small differences though.

    Class specific attributes:
        poker_room        -- FTP
        tournament_level  -- None
        buyin             -- None
        rake              -- None
        currency          -- None
        table_name        -- just a number, but str type

    Extra attributes:
        flop_pot          -- pot size on the flop, before actions
        flop_num_players  -- number of players seen the flop
        turn_pot          -- pot size before turn
        turn_num_players  -- number of players seen the turn
        river_pot         -- pot size before river
        river_num_players -- number of players seen the river
        tournament_name   -- ex. "$750 Guarantee", "$5 Sit & Go (Super Turbo)"

    """
    poker_room = 'FTP'
    date_format = '%H:%M:%S ET - %Y/%m/%d'

    _split_pattern = re.compile(r" ?\*\*\* ?\n?|\n")
    _header_pattern = re.compile(r"""
                        ^Full[ ]Tilt[ ]Poker[ ]                 # Poker Room
                        Game[ ]\#(?P<ident>\d*):[ ]             # Hand number
                        (?P<tournament_name>.*)[ ]              # Tournament name
                        \((?P<tournament_ident>\d*)\),[ ]       # Tournament Number
                        Table[ ](?P<table_name>\d*)[ ]-[ ]      # Table name
                        (?P<limit>NL)[ ]                        # limit
                        (?P<game>.*)[ ]-[ ]                     # game
                        (?P<sb>.*)/(?P<bb>.*?)[ ]-[ ]           # blinds
                        .*[ ]                                   # localized date
                        \[(?P<date>.*)\]$                       # ET date
                        """, re.VERBOSE)
    _seat_pattern = re.compile(r"^Seat (\d): (.*) \(([\d,]*)\)$")
    _button_pattern = re.compile(r"^The button is in seat #(\d)$")
    _hole_cards_pattern = re.compile(r"^Dealt to (.*) \[(..) (..)\]$")
    _street_pattern = re.compile(r"\[(.*)\] \(Total Pot: (\d*)\, (\d) Players")

    def __init__(self, hand_text, parse=True):
        super(FullTiltHand, self).__init__(hand_text, parse)

        self._splitted = self._split_pattern.split(self.raw)

        # search split locations (basically empty strings)
        # sections[0] is before HOLE CARDS
        # sections[-1] is before SUMMARY
        self._sections = [ind for ind, elem in enumerate(self._splitted) if not elem]

        if parse:
            self.parse()

    def parse_header(self):
        match = self._header_pattern.match(self._splitted[0])
        self.game_type = 'TOUR'
        self.sb = Decimal(match.group('sb'))
        self.bb = Decimal(match.group('bb'))
        date = ET.localize(datetime.strptime(match.group('date'), self.date_format))
        self.date = date.astimezone(UTC)
        self.game = GAMES[match.group('game')]
        self.limit = match.group('limit')
        self.ident = match.group('ident')
        self.tournament_ident = match.group('tournament_ident')
        self.tournament_name = match.group('tournament_name')
        self.table_name = match.group('table_name')

        self.tournament_level = self.buyin = self.rake = self.currency = None

        self.header_parsed = True

    def parse(self):
        super(FullTiltHand, self).parse()

        self._parse_seats()
        self._parse_hole_cards()
        self._parse_preflop()
        self._parse_street('flop')
        self._parse_street('turn')
        self._parse_street('river')

    def _parse_seats(self):
        # In hh there is no indication of max_players, so init for 9.
        players = [('Empty Seat %s' % num, 0) for num in range(1, 10)]
        for line in self._splitted[1:]:
            match = self._seat_pattern.match(line)
            if not match:
                break
            seat_number = int(match.group(1))
            player_name = match.group(2)
            stack = int(match.group(3).replace(',', ''))
            players[seat_number - 1] = (player_name, stack)
        self.max_players = seat_number
        self.players = OrderedDict(players)

        # one line before the first split.
        button_line = self._splitted[self._sections[0] - 1]
        self.button_seat = int(self._button_pattern.match(button_line).group(1))
        self.button = players[self.button_seat - 1][0]

    def _parse_hole_cards(self):
        hole_cards_line = self._splitted[self._sections[0] + 2]
        match = self._hole_cards_pattern.match(hole_cards_line)
        self.hero = match.group(1)
        self.hero_seat = self.players.keys().index(self.hero) + 1
        self.hero_hole_cards = match.group(2, 3)

    def _parse_preflop(self):
        start = self._sections[0] + 3
        stop = self._sections[1]
        self.preflop_actions = tuple(self._splitted[start:stop])

    def _parse_street(self, street):
        try:
            start = self._splitted.index(street.upper()) + 1
            self._parse_boardline(start, street)
            stop = self._splitted.index('', start + 1)
            street_actions = self._splitted[start + 1:stop]
            setattr(self, "%s_actions" % street, tuple(street_actions) if street_actions else None)
        except ValueError:
            setattr(self, street, None)
            setattr(self, '%s_actions' % street, None)
            setattr(self, '%s_pot' % street, None)
            setattr(self, '%s_num_players' % street, None)

    def _parse_boardline(self, start, street):
        """Parse pot, num players and cards."""
        # Exceptions caught in _parse_street.
        board_line = self._splitted[start]
        match = self._street_pattern.match(board_line)

        cards = match.group(1)
        setattr(self, street, tuple(cards.split()))

        pot = match.group(2)
        setattr(self, "%s_pot" % street, Decimal(pot))

        num_players = int(match.group(3))
        setattr(self, "%s_num_players" % street, num_players)

