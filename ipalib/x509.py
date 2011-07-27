# Authors:
#   Rob Crittenden <rcritten@redhat.com>
#
# Copyright (C) 2010  Red Hat
# see file 'COPYING' for use and warranty information
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Certificates should be stored internally DER-encoded. We can be passed
# a certificate several ways: read if from LDAP, read it from a 3rd party
# app (dogtag, candlepin, etc) or as user input. The normalize_certificate()
# function will convert an incoming certificate to DER-encoding.

# Conventions
#
# Where possible the following naming conventions are used:
#
# cert: the certificate is a PEM-encoded certificate
# dercert: the certificate is DER-encoded
# nsscert: the certificate is an NSS Certificate object
# rawcert: the cert is in an unknown format

import os
import sys
import base64
import nss.nss as nss
from nss.error import NSPRError
from ipapython import ipautil
from ipalib import api
from ipalib import _
from ipalib import util
from ipalib import errors

PEM = 0
DER = 1

def valid_issuer(issuer, realm):
    return issuer in ('CN=%s Certificate Authority' % realm,
                      'CN=Certificate Authority,O=%s' % realm,)

def strip_header(pem):
    """
    Remove the header and footer from a certificate.
    """
    s = pem.find("-----BEGIN CERTIFICATE-----")
    if s >= 0:
        e = pem.find("-----END CERTIFICATE-----")
        pem = pem[s+27:e]

    return pem

def load_certificate(data, datatype=PEM, dbdir=None):
    """
    Given a base64-encoded certificate, with or without the
    header/footer, return a request object.

    Returns a nss.Certificate type
    """
    if type(data) in (tuple, list):
        data = data[0]

    if (datatype == PEM):
        data = strip_header(data)
        data = base64.b64decode(data)

    if dbdir is None:
        if 'in_tree' in api.env:
            if api.env.in_tree:
                dbdir = api.env.dot_ipa + os.sep + 'alias'
            else:
                dbdir = "/etc/httpd/alias"
            nss.nss_init(dbdir)
        else:
            nss.nss_init_nodb()
    else:
        nss.nss_init(dbdir)


    return nss.Certificate(buffer(data))

def load_certificate_from_file(filename, dbdir=None):
    """
    Load a certificate from a PEM file.

    Returns a nss.Certificate type
    """
    fd = open(filename, 'r')
    data = fd.read()
    fd.close()

    return load_certificate(file, PEM, dbdir)

def get_subject(certificate, datatype=PEM, dbdir=None):
    """
    Load an X509.3 certificate and get the subject.
    """

    nsscert = load_certificate(certificate, datatype, dbdir)
    return nsscert.subject

def get_serial_number(certificate, datatype=PEM, dbdir=None):
    """
    Return the decimal value of the serial number.
    """
    nsscert = load_certificate(certificate, datatype, dbdir)
    return nsscert.serial_number

def make_pem(data):
    """
    Convert a raw base64-encoded blob into something that looks like a PE
    file with lines split to 64 characters and proper headers.
    """
    pemcert = '\n'.join([data[x:x+64] for x in range(0, len(data), 64)])
    return '-----BEGIN CERTIFICATE-----\n' + \
    pemcert + \
    '\n-----END CERTIFICATE-----'

def normalize_certificate(rawcert):
    """
    Incoming certificates should be DER-encoded. If not it is converted to
    DER-format.

    Note that this can't be a normalizer on a Param because only unicode
    variables are normalized.
    """
    if not rawcert:
        return None

    rawcert = strip_header(rawcert)

    if util.isvalid_base64(rawcert):
        try:
            dercert = base64.b64decode(rawcert)
        except Exception, e:
            raise errors.Base64DecodeError(reason=str(e))
    else:
        dercert = rawcert

    # At this point we should have a certificate, either because the data
    # was base64-encoded and now its not or it came in as DER format.
    # Let's decode it and see. Fetching the serial number will pass the
    # certificate through the NSS DER parser.
    try:
        serial = unicode(get_serial_number(dercert, DER))
    except NSPRError, nsprerr:
        if nsprerr.errno == -8183: # SEC_ERROR_BAD_DER
            raise errors.CertificateFormatError(error='improperly formatted DER-encoded certificate')
        else:
            raise errors.CertificateFormatError(error=str(nsprerr))

    return dercert

def write_certificate(rawcert, filename):
    """
    Write the certificate to a file in PEM format.

    The cert value can be either DER or PEM-encoded, it will be normalized
    to DER regardless, then back out to PEM.
    """
    dercert = normalize_certificate(rawcert)

    try:
        fp = open(filename, 'w')
        fp.write(make_pem(base64.b64encode(dercert)))
        fp.close()
    except (IOError, OSError), e:
        raise errors.FileError(reason=str(e))

def verify_cert_subject(ldap, hostname, dercert):
    """
    Verify that the certificate issuer we're adding matches the issuer
    base of our installation.

    This assumes the certificate has already been normalized.

    This raises an exception on errors and returns nothing otherwise.
    """
    nsscert = load_certificate(dercert, datatype=DER)
    subject = str(nsscert.subject)
    issuer = str(nsscert.issuer)

    # Handle both supported forms of issuer, from selfsign and dogtag.
    if (not valid_issuer(issuer, api.env.realm)):
        raise errors.CertificateOperationError(error=_('Issuer "%(issuer)s" does not match the expected issuer') % \
        {'issuer' : issuer})

if __name__ == '__main__':
    # this can be run with:
    # python ipalib/x509.py < /etc/ipa/ca.crt

    from ipalib import api
    api.bootstrap()
    api.finalize()

    nss.nss_init_nodb()

    # Read PEM certs from stdin and print out its components

    certlines = sys.stdin.readlines()
    cert = ''.join(certlines)

    nsscert = load_certificate(cert)

    print nsscert
