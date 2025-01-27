import html
import inspect
import json
import os
import types
import urllib.parse

from bs4 import BeautifulSoup
from copy import copy
from dataclasses import fields, is_dataclass
from typing import Any, Optional, Type, TypeVar, Union, Dict, get_args, get_origin


class ParseException(Exception):
    def __init__(self, message:str) -> None:
        super().__init__(message)

    def __str__(self) -> str:
        return f"Parse Exception - {super().__str__()}"


def parseHumanReadableSize(size:int) -> str:
    for suffix in ["bytes", "KB", "MB", "GB", "TB", "PB"]:
        if size < 1024:
            return f"{size:.3f} {suffix}"
        size/= 1024 

def parseType(value:str|type) -> type | None:

    valueOrigin = get_origin(value)
    valueType = type( valueOrigin if valueOrigin else value )

    if valueType is type:
        return value

    if valueType is str:

        # check for builtin type
        if value in __builtins__:
            return __builtins__[value]

        splitValue = [name for name in value.split('.')]
        if len(splitValue) == 0:
            return None

        # Search backwards through stack frames tying to load the desired type
        # TODO: make this more robust and add support for dynamically loading modules
        #       example: if we call parseType from util.foo with value = 'hello.world'
        #                we should also try to load the util.foo.hello module and instantiate world
        searchedModules = set()
        stackFrames = inspect.stack()
        for i in range(1, len(stackFrames)):

            callerStack = stackFrames[i]
            callerFrame = callerStack.frame
            callerModule = inspect.getmodule(callerFrame)

            if callerModule is None or callerModule in searchedModules:
                continue

            # Note: this loop always runs at least once
            result = callerModule
            for name in splitValue:
                result = getattr(result, name, None)
                if result is None:
                    break
                
            if result is not None:
                return result

            searchedModules.add(callerModule)

    return None 


ParseT = TypeVar("ParseT")
def parseValue(value, ParseT:Type[ParseT]=Any, raiseException:bool = True) -> ParseT | None:

    # Note: we return a copy of the value so modifying parsed data won't modify the original
    if ParseT == Any: 
        return copy(value)    

    # handle parameterized types. Ex: list[int]
    ParseTOrigin = get_origin(ParseT)
    if ParseTOrigin:
        ParseTArgs = get_args(ParseT)

        # Recursively parse to first union value
        if ParseTOrigin in (Union, types.UnionType):
        
            for ArgT in ParseTArgs:

                result = parseValue(value, ArgT, raiseException=False)
                if result is not None:
                    return result
                            
            if raiseException:
                raise ParseException(f"Failed to parse '{type(value)}' as: '{ParseT}' | Value = '{value}' ")
            return None


        numParseTArgs = len(ParseTArgs)

        # parse dicts
        if ParseTOrigin == dict:
            if raiseException:
                raise ParseException(f"Failed to parse value of type '{type(value)}' as '{ParseTOrigin}' - parameterized dict parsing not implemented yet'")
            return None

        # parse lists/tuple/sets
        if ParseTOrigin in [list, set, tuple]:
            if numParseTArgs == 0:
                parsedList = [v for v in value]

            else:
                assert numParseTArgs == 1

                # parse all our elements to match ArgT
                ArgT = parseType(ParseTArgs[0])
                parsedList = [parseValue(v, ArgT, raiseException=raiseException) for v in value]

            return ParseTOrigin(parsedList)
            

    # check if value is an instance of ParseT
    # Note: Python doesn't support checking isinstance(x, 'origin[args...]') yet, so we strip off args 
    ParseInstanceT = ParseTOrigin if ParseTOrigin else ParseT
    if isinstance(value, ParseInstanceT):
        return copy(value)


    # try to construct the dataclass from a dict
    if is_dataclass(ParseT) and isinstance(value, dict):
        try:                
            # parse fields to make sure everything initializes to correct type
            parsedArgs = {}
            for field in fields(ParseT):
                if field.name in value:
                    parsedArgs[field.name] = parseValue(value[field.name], parseType(field.type), raiseException=True)

            return ParseT(**parsedArgs)
        
        except:
            pass

    # try to construct the object directly
    try:
        return ParseT(value)
    except:
        pass

    if raiseException:
        raise ParseException(f"Failed to parse '{type(value)}' to '{ParseT}' | Value = '{value}'")
    return None


KeyT   = TypeVar("KeyT")
ValueT = TypeVar("ValueT")
class ParsableDictionary(Dict[Type[KeyT], Type[ValueT]]):

    ParseT = TypeVar("ParseT")
    def parse(self, key, ParseT:Type[ParseT]=Any) -> ParseT:
        if key not in self:
            raise ParseException(f"Missing required '{key}' key in: '{self}'")
        
        return parseValue(self[key], ParseT)


    DefaultT = TypeVar("DefaultT")
    ParseT   = TypeVar("ParseT")
    def parseDefault(self, key, defaultValue:DefaultT|None = None, ParseT:Type[ParseT]|None = None) -> DefaultT | ParseT:
        if key not in self:
            return defaultValue
        
        if ParseT is None:
            # infer ParseT from default type
            ParseT = Any if defaultValue is None else type(defaultValue)

        return parseValue(self[key], ParseT)

    
    
    ObjT = TypeVar("ObjT")
    def instantiate(self, ObjT:Type[ObjT]) -> ObjT:
        return parseValue(self, ObjT)
         
    def __str__(self) -> str:
        return f"ParsableDictionary {{ {super().__str__()} }}"
    

def parseGetParams(url:str) -> ParsableDictionary:
    parsedUrl = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsedUrl.query)    

    result = ParsableDictionary() 
    for key, val in params.items():

        if len(val) != 1:
            raise ParseException(f"Expected 1 value for get param '{key}', got '{len(val)}'")

        result[key] = val[0]

    return result


def parseJsonDict(jsonStr:str) -> ParsableDictionary:
    rawDict = json.loads(jsonStr)
    return ParsableDictionary(rawDict)

def parseJsonList(jsonStr:str) -> list[ParsableDictionary]:
    rawList = json.loads(jsonStr)
    return [ ParsableDictionary(elmt) for elmt in rawList ]


def parseSoup(htmlSoup:BeautifulSoup, requiredAttributes:list[str] = []) -> BeautifulSoup:

    # make sure soup has required attributes
    for attributeName in requiredAttributes:    
        if attributeName not in htmlSoup.attrs:
            raise ParseException(f"Missing required '{attributeName}' attribute in html soup: '{htmlSoup}'")

    return htmlSoup

def parseSoupElements(htmlSoup:BeautifulSoup, elementName:str, attrs:dict = {}, requiredAttributes:list[str] = []) -> list[BeautifulSoup]:
    elements:list[BeautifulSoup] = htmlSoup.find_all(elementName, attrs=attrs)
    return [parseSoup(elmt) for elmt in elements]

def parseSoupElement(htmlSoup:BeautifulSoup, elementName:str, attrs:dict = {}, requiredAttributes:list[str] = []) -> BeautifulSoup:

    # Grab html element
    elements:list[BeautifulSoup] = htmlSoup.find_all(elementName, attrs=attrs)

    numElements = len(elements)
    if numElements != 1:
        raise ParseException(f"Expected 1 '{elementName}' element, got {numElements} | required attrs: {attrs}")
    
    elementSoup = elements[0]
    return parseSoup(elementSoup, requiredAttributes=requiredAttributes)


def parseSoupElementsByName(htmlSoup:BeautifulSoup, nameAttribute:str, requiredAttributes:list[str] = []) -> list[BeautifulSoup]:

    elements = htmlSoup.find_all(attrs={"name": nameAttribute})
    return [parseSoup(elmt, requiredAttributes=requiredAttributes) for elmt in elements] 


def parseHtmlElements(html:str, elementName:str, attrs:dict = {}, requiredAttributes:list[str] = []) -> list[BeautifulSoup]:
    return parseSoupElements(BeautifulSoup(html, 'html.parser'), elementName=elementName, attrs=attrs, requiredAttributes=requiredAttributes)

def parseHtmlElement(html:str, elementName:str, attrs:dict = {}, requiredAttributes:list[str] = []) -> BeautifulSoup:
    return parseSoupElement(BeautifulSoup(html, 'html.parser'), elementName=elementName, attrs=attrs, requiredAttributes=requiredAttributes)

def parseHtmlElementsByName(html:str, nameAttribute:str, requiredAttributes:list[str] = []) -> list[BeautifulSoup]:
    return parseSoupElementsByName(BeautifulSoup(html, 'html.parser'), nameAttribute=nameAttribute, requiredAttributes=requiredAttributes)


def parseStripedHtmlString(htmlStr:str, emptyValue:str = "") -> str:
    result = html.unescape(htmlStr).strip()
    return result if result else emptyValue

def parseFileExtensionFromUrl(url:str) -> str:
    extension = os.path.splitext(urllib.parse.urlsplit(url)[2])[1]
    
    if len(extension) > 0 and extension[0] == os.path.extsep:
        return extension[1:]
    
    return extension