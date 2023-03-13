# -*- coding: utf-8 -*-
# ***************************************************************************
# *   Copyright (c) 2014 sliptonic <shopinthewoods@gmail.com>               *
# *   Copyright (c) 2018, 2019 Gauthier Briere                              *
# *   Copyright (c) 2019, 2020 Schildkroet                                  *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful,            *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Lesser General Public License for more details.                   *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with FreeCAD; if not, write to the Free Software        *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

import FreeCAD
from FreeCAD import Units
import Path
import Path.Base.Util as PathUtil
import Path.Post.Utils as PostUtils
import PathScripts.PathUtils as PathUtils
import argparse
import datetime
import shlex
import re

class PostProcessorArgument:
    def __init__(self, name, default, description, parser):
        self.name = name
        self.description = description
        self.default = default
        self.parse = parser

    @classmethod
    def bool(cls, name, default, description)
        def parser(input):
            if input is None:
                return (default, None)
            if str(input).lower() == "true":
                return (True, None)
            if str(input).lower() == "false":
                return (False, None)
            return (None, "Invalid boolean")

        return PostProcessorArgument(name, default, description, parser)

class GCodeUnit:
    IMPERIAL = GCodeUnit("G20", "in", "in/min")
    METRIC = GCodeUnit("G21", "mm", "mm/min")

    def __init__(self, command, unit, speed_unit):
        self.command = command;
        self.unit = unit
        self.speed_unit = speed_unit
        # TODO these conversions don't work.  We need to know the "FROM" units

    def convertPosition(self, value):
        return Units.Quantity(value, FreeCAD.Units.Length).getValueAs(self.unit)

    def convertSpeed(self, value):
        return Units.Quantity(value, FreeCAD.Units.Velocity)
            .getValueAs(self.speed_unit)

class Mode:
    ABSOLUTE = "Absolute"
    RELATIVE = "Relative"

class Format:
    POSITION = "Position"
    XYZ = {
        "X": Format.POSITION,
        "Y": Format.POSITION,
        "Z": Format.POSITION,
    }

    ROTATION = "Rotation
    ABC = {
        "A": Format.ROTATION,
        "B": Format.ROTATION,
        "C": Format.ROTATION,
    }

    ARC = "Arc"
    IJK = {
        "I": Format.ARC,
        "J": Format.ARC,
        "K": Format.ARC,
    }

    RADIUS = "Radius"
    R = {
        "R": Format.RADIUS,
    }

    FEED = "Feed"
    F = {
        "F": Format.FEED,
    }

class PostProcessorBase:
    """
    Base class for gcode post processors

    Assumptions:
        Input Units: Metric
        Input Mode: Absolute distance mode
    """

    COMMENTS: PostProcessorArgument.bool("Comments", True,
        "Output comments")
    HEADERS: PostProcessorArgument.bool("Header", True,
        "Output Headers")
    LINE_NUMBERS: PostProcessorArgument.bool("Line Numbers", False,
        "Include line number prefix")
    LINE_NUMBER_START: PostProcessorArgument.int("Line Number Start", 100,
        "Offset first line number by this value")
    LINE_NUMBER_INCREMENT: PostProcessorArgument.int("Line Number Increment", 10,
        "Increase line number by this amount for each subsequent command")
    SHOW_EDITOR: PostProcessorArgument.bool("Show Editor", True,
        "Display the generated file after post-processing completes")
    PRECISION: PostProcessorArgument.int("Precision", 3,
        "Number of digits of precision")
    PREAMBLE: PostProcessorArgument.str("Preamble", "G17 G90",
        "Set commands to be issued before the first command")
    POSTAMBLE: PostProcessorArgument.str("Postamble", "M5\nG17 G90\n;M2",
        "Set commands to be issued after the last command")
    PRE_OPERATION: PostProcessorArgument.str("Pre Operation Commands", "",
        "Commands to run before each operation")
    POST_OPERATION: PostProcessorArgument.str("Post Operation Commands", "",
        "Commands to run before each operation")
    INCHES: PostProcessorAgument.bool("Inches", False,
        "Convert output for US imperial mode (G20)")

    @classmethod
    def arguments(cls):
        args = {}
        for k, v in cls.__annotations__.items():
            if isinstance(v, PostProcessorArgument):
                args[k] = v
        return args

    @classmethod
    def tooltip(cls):
        return cls.__doc__

    def __init__(self, options):
        for key, arg in type(self).arguments():
            val, error = arg.parse(options.get(key))
            if error:
                raise Exception(error)

            setattr(self, key, arg.value, val)

        self.RAPID_COMMANDS = ["G0", "G00"]
        self.LINEAR_COMMANDS = ["G1", "G01"]
        self.ARC_COMMANDS = ["G2", "G02", "G3", "G03"]
        self.DWELL_COMMANDS = ["G4", "G04"]
        self.UNIT_COMMANDS = [GCodeUnit.IMPERIAL.command, GCodeUnit.METRIC.command]
        self.ABSOLUTEMOVE_COMMAND = "G90"
        self.RELATIVEMOVE_COMMAND = "G91"
        self.ABSOLUTEARC_COMMAND = "G90.1"
        self.RELATIVEARC_COMMAND = "G91.1"
        self.MODE_COMMANDS = [
            self.ABSOLUTEMOVE_COMMAND,
            self.RELATIVEMOVE_COMMAND,
            self.ABSOLUTEARC_COMMAND,
            self.RELATIVEARC_COMMAND
        ]


    def execute(self, job):
        name = type(self).__name__
        print("Post Processor: " + name + " postprocessing...")

        gcode = ""

        # write header
        if self.HEADER:
            gcode += self.comment("Exported by FreeCAD")
            gcode += self.comment("Post Processor: %s" % name)
            gcode += self.comment("Output Time: %s" % str(datetime.datetime.now()))

        # Trackers
        self.location = {}  # keep track for no repeats
        self.lineNumber = self.LINE_NUMBER_START
        self.units = None # keep track of units
        # TODO defaults
        self.moveMode = Mode.ABSOLUTE
        self.arcMode = Mode.ABSOLUTE

        # Write the preamble
        if self.PREAMBLE:
            if self.COMMENTS:
                gcode += self.comment("Begin preamble")
            gcode += self.processBlock(self.PREAMBLE)

        # If units are not set in preamble, set to default
        if self.units is None:
            if self.INCHES:
                self.units = GCodeUnit.IMPERIAL
            else:
                self.units = GCodeUnit.METRIC
            gcode += self.line(self.units.command)

        for op, placement, tool in job.enumerateOperations():
            gcode += self.processOperation(op, placement, tool)

        # Write the preamble
        if self.POSTAMBLE:
            if self.COMMENTS:
                gcode += self.comment("Begin postamble")
            gcode += self.processBlock(self.POSTAMBLE)

    def formatFloat(self, value):
        return format(".%sf" % self.PRECISION, value)
    def formatInt(self, value):
        return str(int(value))

    def processBlock(self, block):
        gcode = ""
        for line in block.splitlines(True):
            gcode += self.line(line)

            # Update trackers
            if GCodeUnit.METRIC.command in line:
                self.units = GCodeUnit.METRIC
            elif GCodeUnit.IMPERIAL.command in line:
                self.units = GCodeUnit.IMPERIAL

            # TODO update location?

        return gcode

    def processCoolantMode(self, op):
        coolantMode = None
        if hasattr(op, "CoolantMode"):
            coolantMode = op.CoolantMode
        elif hasattr(op, "Base") and hasattr(op.Base, "CoolantMode"):
            coolantMode = op.Base.CoolantMode

        def start_coolant():
            gcode = ""
            # turn coolant on if required
            if coolantMode:
                if self.COMMENTS:
                    gcode += self.comment("Coolant On: %s" % coolantMode)
                if coolantMode == "Flood":
                    gcode += self.line("M8")
                if coolantMode == "Mist":
                    gcode += self.line("M7")
            return gcode

        def stop_coolant():
            gcode = ""
            # turn coolant off if required
            if coolantMode:
                if self.COMMENTS:
                    gcode += self.comment("Coolant Off: %s" % coolantMode)
                gcode += self.line("M9")
            return gcode

        return start_coolant, stop_coolant

    def formatParameter(self, param, value, format):
        # TODO keep track of when units change...
        # TODO move/arc mode
        match format:
            case Format.POSITION:
                pos = self.units.convertPosition(value)
                value = self.formatFloat(pos)
            case Format.ARC:
                arc = self.units.convertPosition(value)
                value = self.formatFloat(arc)
            case Format.RADIUS:
                radius = self.units.convertPosition(value)
                value = self.formatFloat(radius)
            case Format.ROTATION:
                value = self.formatFloat(value)
            case Format.FEED:
                speed = self.units.convertSpeed(value)
                if speed <= 0.0:
                    raise Exception("Invalid value for feed rate: %s" % value)
                value = self.formatFloat(speed)
        return "%s%s" % (param, value)
    """
        if param in ["D", "H", "L", "P", "S", "T"]:
            # Integers:
            # D: Cutter Compensation
            # H: Tool Length / Cutter Compensation
            # L: Fixed cycle loop count / Register
            # P: Parameter Address
            # S: Spindle Speed (TODO may need conversion)
            # T: Tool Selection
            return param + self.formatInt(value)
        elif param in ["X", "Y", "Z", "U", "V", "W", "I", "J", "K", "R", "Q"]:
            return param + self.formatFloat(self.units.convertPosition(value))
    """

    def formatCommand(self, command, order):
        for param in command.Parameters.items():
            if param not in order:
                raise Exception("Unexpected Parameter '%s' in command '%s'" % param, command)

        gcode = command.Name
        for param, format in order.items():
            value = command.Parameters.get(param)
            if not value:
                continue

            gcode += " " + self.formatParameter(param, value, format)
        return self.line(gcode)

    def moveRapid(self, command):
        return self.formatCommand(command, Format.XYZ | Format.ABC | Format.F)
    def moveLinear(self, command):
        return self.formatCommand(command, Format.XYZ | Format.ABC | Format.F)
    def moveArc(self, command):
        return self.formatCommand(command, Format.XYZ | Format.ABC | Format.IJK | Format.R | Format.F)

    def dwell(self, command):
        # (PUX) Seconds or ms, depends on machine
        if "P" not in command:
            raise Exception("Expected P in %s", command)
        return self.line("%s P%s" % (command.Name, command.Parameters["P"]))

    def switchUnit(self, command):
        if command == GCodeUnit.METRIC.command:
            self.units = GCodeUnit.METRIC
        if command == GCodeUnit.IMPERIAL.command:
            self.units = GCodeUnit.IMPERIAL

        if command.Parameters:
            raise Exception("Unexpected parameters to Switch Unit: %s" % command)

        return self.line(command.Name)

    def switchMode(self, command):
        if command == self.ABSOLUTEMOVE_COMMAND:
            self.moveMode = Mode.ABSOLUTE
        if command == self.RELATIVEMOVE_COMMAND:
            self.moveMode = Mode.RELATIVE
        if command == self.ABSOLUTEARC_COMMAND:
            self.arcMode = Mode.ABSOLUTE
        if command == self.RELATIVEARC_COMMAND:
            self.arcMode = Mode.RELATIVE

        if command.Parameters:
            raise Exception("Unexpected parameters to Switch Mode: %s" % command)

        return self.line(command.Name)

    def formatCommand(self, command):
        if command.Name in self.RAPID_COMMANDS:
            return self.moveRapid(command)
        if command.Name in self.LINEAR_COMMANDS:
            return self.moveLinear(command)
        if command.Name in self.ARC_COMMANDS:
            return self.moveArc(command)
        if command.Name in self.DWELL_COMMANDS:
            return self.dwell(command)
        if command.Name in self.UNIT_COMMANDS:
            return self.switchUnit(command)
        if command.Name in self.MODE_COMMANDS:
            return self.switchMode(command)


    def processOperation(self, op, placement, tool):
        gcode = ""
        if self.COMMENTS:
            gcode += self.comment("Begin operation: %s" % op.Label)
        if self.PRE_OPERATION:
            gcode += self.processBlock(self.PRE_OPERATION)

        start_coolant, stop_coolant = self.processCoolantMode(op)

        start_coolant()

        for command in op.Path:
            command.Name
            command.Parameters
            paramOrder

        stop_coolant()

        if self.COMMENTS:
            gcode += self.comment("Finish operation: %s" % op.Label)
        if self.POST_OPERATION:
            gcode += self.processBlock(self.POST_OPERATION)

        return gcode

    def comment(self, comment):
        return command("", comment)

    def line(self, command, comment = None):
        fmt = "%s"
        args = [command]

        if self.LINE_NUMBERS:
            fmt = "N%d " + fmt
            args = [self.lineNumber] + args
            self.lineNumber += self.LINE_NUMBER_INCREMENT

        if comment:
            if command:
                fmt += " "
            fmt += "(%s)"
            args += [comment]

        fmt += "\n"
        return fmt % tuple(args)



"""
# Commands defined in operations/generator
G0 rapid
G1 move
G2 arc
G3 arc
G38.2 probe
G40 Tool Radius Compensation Off
G73 peck drill
G80 Cancel drill cycle
G81 drill
G82 drill w/ dwell
G83 peck drill
G90 Absolute distance mode
G98 drill return
G99 drill return

Commands referenced in path source code
G0 188
G00 31
G01 11
G02 10
G03 20
G04 1
G1 112
G10 1
G17 9
G18 1
G19 1
G2 35
G20 45
G21 37
G28 1
G3 43
G38.2 1
G4 12
G40 5
G41 1
G42 2
G42.1 1
G49 3
G51 1
G53 1
G54 9
G55 4
G56 4
G57 4
G58 4
G59 6
G59.1 3
G59.2 3
G59.3 3
G59.4 3
G59.5 3
G59.6 3
G59.7 3
G59.8 3
G59.9 3
G64 1
G70 3
G71 1
G73 1
G77 2
G80 17
G81 6
G82 26
G83 29
G84 3
G85 1
G89 1
G90 45
G90.1 1
G91 42
G91.1 1
G94 1
G95 1
G97 1
G98 14
G99 20
"""



# ***************************************************************************
# * Internal global variables
# ***************************************************************************
SUPPRESS_COMMANDS = []  # These commands are ignored by commenting them out
COMMAND_SPACE = " "
# Global variables storing current position
CURRENT_X = 0
CURRENT_Y = 0
CURRENT_Z = 0

def export(objectslist, filename, argstring):

    if not processArguments(argstring):
        return None

    global UNITS
    global UNIT_FORMAT
    global UNIT_SPEED_FORMAT
    global MOTION_MODE
    global SUPPRESS_COMMANDS

    print("Post Processor: " + __name__ + " postprocessing...")
    gcode = ""

    # write header
    if OUTPUT_HEADER:
        gcode += linenumber() + "(Exported by FreeCAD)\n"
        gcode += linenumber() + "(Post Processor: " + __name__ + ")\n"
        gcode += linenumber() + "(Output Time:" + str(datetime.datetime.now()) + ")\n"

    # Check canned cycles for drilling
    if TRANSLATE_DRILL_CYCLES:
        if len(SUPPRESS_COMMANDS) == 0:
            SUPPRESS_COMMANDS = ["G99", "G98", "G80"]
        else:
            SUPPRESS_COMMANDS += ["G99", "G98", "G80"]

    # Write the preamble
    if OUTPUT_COMMENTS:
        gcode += linenumber() + "(Begin preamble)\n"
    for line in PREAMBLE.splitlines(True):
        gcode += linenumber() + line
    # verify if PREAMBLE have changed MOTION_MODE or UNITS
    if "G90" in PREAMBLE:
        MOTION_MODE = "G90"
    elif "G91" in PREAMBLE:
        MOTION_MODE = "G91"
    else:
        gcode += linenumber() + MOTION_MODE + "\n"
    if "G21" in PREAMBLE:
        UNITS = "G21"
        UNIT_FORMAT = "mm"
        UNIT_SPEED_FORMAT = "mm/min"
    elif "G20" in PREAMBLE:
        UNITS = "G20"
        UNIT_FORMAT = "in"
        UNIT_SPEED_FORMAT = "in/min"
    else:
        gcode += linenumber() + UNITS + "\n"

    for obj in objectslist:
        # Debug...
        # print("\n" + "*"*70)
        # dump(obj)
        # print("*"*70 + "\n")
        if not hasattr(obj, "Path"):
            print(
                "The object "
                + obj.Name
                + " is not a path. Please select only path and Compounds."
            )
            return

        # Skip inactive operations
        if PathUtil.opProperty(obj, "Active") is False:
            continue

        # do the pre_op
        if OUTPUT_BCNC:
            gcode += linenumber() + "(Block-name: " + obj.Label + ")\n"
            gcode += linenumber() + "(Block-expand: 0)\n"
            gcode += linenumber() + "(Block-enable: 1)\n"
        if OUTPUT_COMMENTS:
            gcode += linenumber() + "(Begin operation: " + obj.Label + ")\n"
        for line in PRE_OPERATION.splitlines(True):
            gcode += linenumber() + line

        # get coolant mode
        coolantMode = "None"
        if (
            hasattr(obj, "CoolantMode")
            or hasattr(obj, "Base")
            and hasattr(obj.Base, "CoolantMode")
        ):
            if hasattr(obj, "CoolantMode"):
                coolantMode = obj.CoolantMode
            else:
                coolantMode = obj.Base.CoolantMode

        # turn coolant on if required
        if OUTPUT_COMMENTS:
            if not coolantMode == "None":
                gcode += linenumber() + "(Coolant On:" + coolantMode + ")\n"
        if coolantMode == "Flood":
            gcode += linenumber() + "M8" + "\n"
        if coolantMode == "Mist":
            gcode += linenumber() + "M7" + "\n"

        # Parse the op
        gcode += parse(obj)

        # do the post_op
        if OUTPUT_COMMENTS:
            gcode += linenumber() + "(Finish operation: " + obj.Label + ")\n"
        for line in POST_OPERATION.splitlines(True):
            gcode += linenumber() + line

        # turn coolant off if required
        if not coolantMode == "None":
            if OUTPUT_COMMENTS:
                gcode += linenumber() + "(Coolant Off:" + coolantMode + ")\n"
            gcode += linenumber() + "M9" + "\n"

    if RETURN_TO:
        gcode += linenumber() + "G0 X%s Y%s\n" % tuple(RETURN_TO)

    # do the post_amble
    if OUTPUT_BCNC:
        gcode += linenumber() + "(Block-name: post_amble)\n"
        gcode += linenumber() + "(Block-expand: 0)\n"
        gcode += linenumber() + "(Block-enable: 1)\n"
    if OUTPUT_COMMENTS:
        gcode += linenumber() + "(Begin postamble)\n"
    for line in POSTAMBLE.splitlines(True):
        gcode += linenumber() + line

    # show the gCode result dialog
    if FreeCAD.GuiUp and SHOW_EDITOR:
        dia = PostUtils.GCodeEditorDialog()
        dia.editor.setText(gcode)
        result = dia.exec_()
        if result:
            final = dia.editor.toPlainText()
        else:
            final = gcode
    else:
        final = gcode

    print("Done postprocessing.")

    # write the file
    gfile = pythonopen(filename, "w")
    gfile.write(final)
    gfile.close()

    return final


def linenumber():
    if not OUTPUT_LINE_NUMBERS:
        return ""
    global LINENR
    global LINEINCR
    s = "N" + str(LINENR) + " "
    LINENR += LINEINCR
    return s


def format_outstring(strTable):
    global COMMAND_SPACE
    # construct the line for the final output
    s = ""
    for w in strTable:
        s += w + COMMAND_SPACE
    s = s.strip()
    return s


def parse(pathobj):

    global DRILL_RETRACT_MODE
    global MOTION_MODE
    global CURRENT_X
    global CURRENT_Y
    global CURRENT_Z

    out = ""
    lastcommand = None
    precision_string = "." + str(PRECISION) + "f"

    params = [
        "X",
        "Y",
        "Z",
        "A",
        "B",
        "C",
        "U",
        "V",
        "W",
        "I",
        "J",
        "K",
        "F",
        "S",
        "T",
        "Q",
        "R",
        "L",
        "P",
    ]

    if hasattr(pathobj, "Group"):  # We have a compound or project.
        if OUTPUT_COMMENTS:
            out += linenumber() + "(Compound: " + pathobj.Label + ")\n"
        for p in pathobj.Group:
            out += parse(p)
        return out

    else:  # parsing simple path
        if not hasattr(
            pathobj, "Path"
        ):  # groups might contain non-path things like stock.
            return out

        if OUTPUT_COMMENTS:
            out += linenumber() + "(Path: " + pathobj.Label + ")\n"

        for c in PathUtils.getPathWithPlacement(pathobj).Commands:
            outstring = []
            command = c.Name

            outstring.append(command)

            # if modal: only print the command if it is not the same as the last one
            if MODAL:
                if command == lastcommand:
                    outstring.pop(0)

            # Now add the remaining parameters in order
            for param in params:
                if param in c.Parameters:
                    if param == "F":
                        if command not in RAPID_MOVES:
                            speed = Units.Quantity(
                                c.Parameters["F"], FreeCAD.Units.Velocity
                            )
                            if speed.getValueAs(UNIT_SPEED_FORMAT) > 0.0:
                                outstring.append(
                                    param
                                    + format(
                                        float(speed.getValueAs(UNIT_SPEED_FORMAT)),
                                        precision_string,
                                    )
                                )
                    elif param in ["T", "H", "S"]:
                        outstring.append(param + str(int(c.Parameters[param])))
                    elif param in ["D", "P", "L"]:
                        outstring.append(param + str(c.Parameters[param]))
                    elif param in ["A", "B", "C"]:
                        outstring.append(
                            param + format(c.Parameters[param], precision_string)
                        )
                    else:  # [X, Y, Z, U, V, W, I, J, K, R, Q] (Conversion eventuelle mm/inches)
                        pos = Units.Quantity(c.Parameters[param], FreeCAD.Units.Length)
                        outstring.append(
                            param
                            + format(
                                float(pos.getValueAs(UNIT_FORMAT)), precision_string
                            )
                        )

            # store the latest command
            lastcommand = command

            # Memorizes the current position for calculating the related movements and the withdrawal plan
            if command in MOTION_COMMANDS:
                if "X" in c.Parameters:
                    CURRENT_X = Units.Quantity(c.Parameters["X"], FreeCAD.Units.Length)
                if "Y" in c.Parameters:
                    CURRENT_Y = Units.Quantity(c.Parameters["Y"], FreeCAD.Units.Length)
                if "Z" in c.Parameters:
                    CURRENT_Z = Units.Quantity(c.Parameters["Z"], FreeCAD.Units.Length)

            if command in ("G98", "G99"):
                DRILL_RETRACT_MODE = command

            if command in ("G90", "G91"):
                MOTION_MODE = command

            if TRANSLATE_DRILL_CYCLES:
                if command in ("G81", "G82", "G83"):
                    out += drill_translate(outstring, command, c.Parameters)
                    # Erase the line we just translated
                    outstring = []

            if SPINDLE_WAIT > 0:
                if command in ("M3", "M03", "M4", "M04"):
                    out += linenumber() + format_outstring(outstring) + "\n"
                    out += (
                        linenumber()
                        + format_outstring(["G4", "P%s" % SPINDLE_WAIT])
                        + "\n"
                    )
                    outstring = []

            # Check for Tool Change:
            if command in ("M6", "M06"):
                if OUTPUT_COMMENTS:
                    out += linenumber() + "(Begin toolchange)\n"
                if not OUTPUT_TOOL_CHANGE:
                    outstring.insert(0, "(")
                    outstring.append(")")
                else:
                    for line in TOOL_CHANGE.splitlines(True):
                        out += linenumber() + line

            if command == "message":
                if OUTPUT_COMMENTS is False:
                    out = []
                else:
                    outstring.pop(0)  # remove the command

            if command in SUPPRESS_COMMANDS:
                outstring.insert(0, "(")
                outstring.append(")")

            # prepend a line number and append a newline
            if len(outstring) >= 1:
                out += linenumber() + format_outstring(outstring) + "\n"

            # Check for comments containing machine-specific commands to pass literally to the controller
            m = re.match(r"^\(MC_RUN_COMMAND: ([^)]+)\)$", command)
            if m:
                raw_command = m.group(1)
                out += linenumber() + raw_command + "\n"

    return out


def drill_translate(outstring, cmd, params):
    global DRILL_RETRACT_MODE
    global MOTION_MODE
    global CURRENT_X
    global CURRENT_Y
    global CURRENT_Z
    global UNITS
    global UNIT_FORMAT
    global UNIT_SPEED_FORMAT

    strFormat = "." + str(PRECISION) + "f"

    trBuff = ""

    if OUTPUT_COMMENTS:  # Comment the original command
        outstring[0] = "(" + outstring[0]
        outstring[-1] = outstring[-1] + ")"
        trBuff += linenumber() + format_outstring(outstring) + "\n"

    # cycle conversion
    # currently only cycles in XY are provided (G17)
    # other plains ZX (G18) and  YZ (G19) are not dealt with : Z drilling only.
    drill_X = Units.Quantity(params["X"], FreeCAD.Units.Length)
    drill_Y = Units.Quantity(params["Y"], FreeCAD.Units.Length)
    drill_Z = Units.Quantity(params["Z"], FreeCAD.Units.Length)
    RETRACT_Z = Units.Quantity(params["R"], FreeCAD.Units.Length)
    # R less than Z is error
    if RETRACT_Z < drill_Z:
        trBuff += linenumber() + "(drill cycle error: R less than Z )\n"
        return trBuff

    if MOTION_MODE == "G91":  # G91 relative movements
        drill_X += CURRENT_X
        drill_Y += CURRENT_Y
        drill_Z += CURRENT_Z
        RETRACT_Z += CURRENT_Z

    if DRILL_RETRACT_MODE == "G98" and CURRENT_Z >= RETRACT_Z:
        RETRACT_Z = CURRENT_Z

    # get the other parameters
    drill_feedrate = Units.Quantity(params["F"], FreeCAD.Units.Velocity)
    if cmd == "G83":
        drill_Step = Units.Quantity(params["Q"], FreeCAD.Units.Length)
        a_bit = (
            drill_Step * 0.05
        )  # NIST 3.5.16.4 G83 Cycle:  "current hole bottom, backed off a bit."
    elif cmd == "G82":
        drill_DwellTime = params["P"]

    # wrap this block to ensure machine MOTION_MODE is restored in case of error
    try:
        if MOTION_MODE == "G91":
            trBuff += linenumber() + "G90\n"  # force absolute coordinates during cycles

        strG0_RETRACT_Z = (
            "G0 Z" + format(float(RETRACT_Z.getValueAs(UNIT_FORMAT)), strFormat) + "\n"
        )
        strF_Feedrate = (
            " F"
            + format(float(drill_feedrate.getValueAs(UNIT_SPEED_FORMAT)), ".2f")
            + "\n"
        )
        print(strF_Feedrate)

        # preliminary movement(s)
        if CURRENT_Z < RETRACT_Z:
            trBuff += linenumber() + strG0_RETRACT_Z
        trBuff += (
            linenumber()
            + "G0 X"
            + format(float(drill_X.getValueAs(UNIT_FORMAT)), strFormat)
            + " Y"
            + format(float(drill_Y.getValueAs(UNIT_FORMAT)), strFormat)
            + "\n"
        )
        if CURRENT_Z > RETRACT_Z:
            # NIST GCODE 3.5.16.1 Preliminary and In-Between Motion says G0 to RETRACT_Z. Here use G1 since retract height may be below surface !
            trBuff += (
                linenumber()
                + "G1 Z"
                + format(float(RETRACT_Z.getValueAs(UNIT_FORMAT)), strFormat)
                + strF_Feedrate
            )
        last_Stop_Z = RETRACT_Z

        # drill moves
        if cmd in ("G81", "G82"):
            trBuff += (
                linenumber()
                + "G1 Z"
                + format(float(drill_Z.getValueAs(UNIT_FORMAT)), strFormat)
                + strF_Feedrate
            )
            # pause where applicable
            if cmd == "G82":
                trBuff += linenumber() + "G4 P" + str(drill_DwellTime) + "\n"
            trBuff += linenumber() + strG0_RETRACT_Z
        else:  # 'G83'
            if params["Q"] != 0:
                while 1:
                    if last_Stop_Z != RETRACT_Z:
                        clearance_depth = (
                            last_Stop_Z + a_bit
                        )  # rapid move to just short of last drilling depth
                        trBuff += (
                            linenumber()
                            + "G0 Z"
                            + format(
                                float(clearance_depth.getValueAs(UNIT_FORMAT)),
                                strFormat,
                            )
                            + "\n"
                        )
                    next_Stop_Z = last_Stop_Z - drill_Step
                    if next_Stop_Z > drill_Z:
                        trBuff += (
                            linenumber()
                            + "G1 Z"
                            + format(
                                float(next_Stop_Z.getValueAs(UNIT_FORMAT)), strFormat
                            )
                            + strF_Feedrate
                        )
                        trBuff += linenumber() + strG0_RETRACT_Z
                        last_Stop_Z = next_Stop_Z
                    else:
                        trBuff += (
                            linenumber()
                            + "G1 Z"
                            + format(float(drill_Z.getValueAs(UNIT_FORMAT)), strFormat)
                            + strF_Feedrate
                        )
                        trBuff += linenumber() + strG0_RETRACT_Z
                        break

    except Exception as e:
        pass

    if MOTION_MODE == "G91":
        trBuff += linenumber() + "G91"  # Restore if changed

    return trBuff


# print(__name__ + ": GCode postprocessor loaded.")
