"""SOAP support module

Based on the XML-RPC Zope support module written by Eric Kidd at UserLand
software, with much help from Jim Fulton at DC.

This code hooks Zope up to Fredrik Lundh's Python SOAP library.
"""

import sys
import types
from string import replace
from zExceptions import Unauthorized
from zope.publisher.xmlrpc import premarshal
from ZSI import TC, ParsedSoap
from ZSI import SoapWriter, Fault
from zope.component import queryUtility
from z3c.soap.interfaces import IZSIRequestType, IZSIResponseType
import ZSI
import logging
import traceback
from zope.interface import implements
from z3c.soap.interfaces import ISOAPResponse


class SOAPParser(object):

    def __init__(self, data):
        self.parsed = ParsedSoap(data)
        self.root = self.parsed.body_root
        self.target = self.root.localName
        self.method = replace(self.target, '.', '/')

    def parse(self):
        data = ZSI._child_elements(self.root)
        if len(data) == 0:
            params = ()
        else:
            resolver = queryUtility(IZSIRequestType, name=self.target)
            if resolver and hasattr(resolver, 'typecode'):
                tc = resolver.typecode
                params = [resolver.typecode.parse(self.root, self.parsed)]

                resolver = queryUtility(IZSIResponseType, name=self.target)
                params.append(resolver)
            else:
                tc = TC.Any()
                params = [tc.parse(e, self.parsed) for e in data]
            params = tuple(params)
        return params


def parse_input(data):
    parser = SOAPParser(data)
    return parser.parse()


class SOAPResponse:
    """Customized Response that handles SOAP-specific details.

    We override setBody to marhsall Python objects into SOAP. We
    also override exception to convert errors to SOAP faults.

    If these methods stop getting called, make sure that ZPublisher is
    using the soap.Response object created above and not the original
    HTTPResponse object from which it was cloned.

    It's probably possible to improve the 'exception' method quite a bit.
    The current implementation, however, should suffice for now.
    """
    implements(ISOAPResponse)
    _contentType = 'text/xml'

    _soap11 = None
    _soap12 = None
    # Because we can't predict what kind of thing we're customizing,
    # we have to use delegation, rather than inheritence to do the
    # customization.

    def __init__(self, real):
        self.__dict__['_real']=real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, v):
        return setattr(self._real, name, v)

    def __delattr__(self, name):
        return delattr(self._real, name)

    def setBody(self, body, title='', is_error=0, bogus_str_search=None):
        if isinstance(body, Fault):
            # Convert Fault object to SOAP response.
            #body = buildSOAP(args=body, config=Config)
            body = ZSI.FaultFromException(body, 0)
            body = body.AsSOAP()
        else:
            # Marshall our body as an SOAP response. Strings will be sent
            # strings, integers as integers, etc. We do *not* convert
            # everything to a string first.
            try:
                target = self._method
                body = premarshal(body)
                #output = StringIO()
                result = body
                if hasattr(result, 'typecode'):
                    tc = result.typecode
                else:
                    tc = TC.Any(aslist=1, pname=target + 'Response')
                    result = [result]
                sw = SoapWriter(nsdict={}, header=True, outputclass=None,
                        encodingStyle=None)
                body = sw.serialize(result, tc).body
            except:
                self.exception()
                return

        # Set our body to the message, and fix our MIME type.
        self._real.setBody(body)
        self._setHeader()
        return self

    def exception(self, fatal=0, info=None,
                  absuri_match=None, tag_search=None):
        # Fetch our exception info. t is type, v is value and tb is the
        # traceback object.
        if type(info) is type(()) and len(info)==3:
            t, v, tb = info
        else:
            t, v, tb = sys.exc_info()

        content = "".join(traceback.format_tb(tb))
        logger = logging.getLogger('Zope')
        logger.info('SOAPException: %s' % tb)
        if t == 'Unauthorized' or t == Unauthorized or (
           isinstance(t, types.ClassType) and issubclass(t, Unauthorized)):
            realm=self._real.realm
            if realm:
                self._real.setHeader('WWW-Authenticate',
                                     'basic realm="%s"' % realm, 1)
                self._real.setStatus(401)
            return None

        # Create an appropriate Fault object. Unfortunately, we throw away
        # most of the debugging information. More useful error reporting is
        # left as an exercise for the reader.
        f=None
        if not isinstance(v, Fault):
            f = ZSI.FaultFromException(u"%s : %s" % (v, content), 0)
        # Do the damage.
        self.setBody(f)
        self._real.setStatus(500)

        return tb

    def _setHeader(self):
        self.setHeader('content-length', len(self._real.body))
        self._real.setHeader('content-type', self._contentType)
        if self._soap11:
            self._real.setHeader('content-type', 'text/xml')
        if self._soap12:
            self._real.setHeader('content-type', 'application/soap+xml')


response=SOAPResponse
