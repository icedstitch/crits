import json

from django.contrib.auth.decorators import user_passes_test
from django.core.urlresolvers import reverse
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render_to_response
from django.template import RequestContext

from crits.core import form_consts
from crits.core.crits_mongoengine import EmbeddedCampaign
from crits.core.data_tools import json_handler, make_ascii_strings
from crits.core.data_tools import make_unicode_strings, make_hex, xor_search
from crits.core.data_tools import xor_string, make_stackstrings
from crits.core.exceptions import ZipFileError
from crits.core.handlers import get_object_types
from crits.core.handsontable_tools import form_to_dict
from crits.core.user_tools import user_can_view_data, user_is_admin
from crits.core.user_tools import get_user_organization
from crits.emails.forms import EmailAttachForm
from crits.objects.forms import AddObjectForm
from crits.samples.forms import UploadFileForm, NewExploitForm, NewBackdoorForm
from crits.samples.forms import BackdoorForm, ExploitForm, XORSearchForm
from crits.samples.forms import UnrarSampleForm
from crits.samples.handlers import handle_uploaded_file, add_new_backdoor
from crits.samples.handlers import add_new_exploit, mail_sample
from crits.samples.handlers import handle_unrar_sample, generate_yarahit_jtable
from crits.samples.handlers import delete_sample, handle_unzip_file
from crits.samples.handlers import get_exploits, add_exploit_to_sample
from crits.samples.handlers import add_backdoor_to_sample, get_source_counts
from crits.samples.handlers import get_sample_details, generate_backdoor_jtable
from crits.samples.handlers import generate_sample_jtable, add_source_to_samples
from crits.samples.handlers import generate_sample_csv, process_bulk_add_md5_sample
from crits.samples.sample import Sample
from crits.stats.handlers import generate_sources
from crits.stats.handlers import generate_exploits


@user_passes_test(user_can_view_data)
def detail(request, sample_md5):
    """
    Generate the sample details page.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param sample_md5: The MD5 of the Sample.
    :type sample_md5: str
    :returns: :class:`django.http.HttpResponse`
    """

    format_ = request.GET.get('format', None)
    template = "samples_detail.html"
    (new_template, args) = get_sample_details(sample_md5,
                                              request.user.username,
                                              format_)
    if new_template:
        template = new_template
    if template == "yaml":
        return HttpResponse(args, mimetype="text/plain")
    elif template == "json":
        return HttpResponse(json.dumps(args), mimetype="application/json")
    return render_to_response(template,
                              args,
                              RequestContext(request))

@user_passes_test(user_can_view_data)
def samples_listing(request,option=None):
    """
    Generate Samples Listing template.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param option: Whether or not we should generate a CSV (yes if option is "csv")
    :type option: str
    :returns: :class:`django.http.HttpResponse`
    """

    if option == "csv":
        return generate_sample_csv(request)
    return generate_sample_jtable(request, option)

@user_passes_test(user_can_view_data)
def backdoors_listing(request,option=None):
    """
    Generate Backdoor Listing template.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param option: Whether or not we should generate a CSV (yes if option is "csv")
    :type option: str
    :returns: :class:`django.http.HttpResponse`
    """

    return generate_backdoor_jtable(request, option)

@user_passes_test(user_can_view_data)
def yarahits_listing(request,option=None):
    """
    Generate YaraHits Listing template.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param option: Whether or not we should generate a CSV (yes if option is "csv")
    :type option: str
    :returns: :class:`django.http.HttpResponse`
    """

    return generate_yarahit_jtable(request, option)

@user_passes_test(user_can_view_data)
def view_upload_list(request, filename, md5s):
    """
    View a list of uploaded files.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param filename: The name of the original file that was uploaded.
    :type filename: str
    :param md5s: The MD5s of the files that were uploaded.
    :type md5s: str
    :returns: :class:`django.http.HttpResponse`
    """

    #convert md5s list from unicode to list
    while md5s.endswith('/'):
        md5s = md5s[:-1]
    import ast
    md5s = ast.literal_eval(md5s)
    return render_to_response('samples_uploadList.html',
                              {'sample_md5': md5s,
                               'archivename': filename},
                              RequestContext(request))

@user_passes_test(user_can_view_data)
def bulk_add_md5_sample(request):
    """
    Bulk add samples via a bulk upload form.

    Args:
        request: The Django context which contains information about the
            session and key/value pairs for the bulk add request

    Returns:
        If the request is not a POST and not a Ajax call then:
            Returns a rendered HTML form for a bulk add of domains
        If the request is a POST and a Ajax call then:
            Returns a response that contains information about the
            status of the bulk add. This may include information
            such as items that failed or successfully added. This may
            also contain helpful status messages about each operation.
    """
    all_obj_type_choices = [(c[0],
                            c[0],
                            {'datatype':c[1].keys()[0],
                            'datatype_value':c[1].values()[0]}
                            ) for c in get_object_types(False)]

    formdict = form_to_dict(UploadFileForm(request.user, request.POST, request.FILES))
    objectformdict = form_to_dict(AddObjectForm(request.user, all_obj_type_choices))

    if request.method == "POST" and request.is_ajax():
        response = process_bulk_add_md5_sample(request, formdict);

        return HttpResponse(json.dumps(response,
                            default=json_handler),
                            mimetype='application/json')
    else:
        return render_to_response('bulk_add_default.html',
                                  {'formdict': formdict,
                                  'objectformdict': objectformdict,
                                  'title': "Bulk Add Samples",
                                  'table_name': 'sample',
                                  'local_validate_columns': [form_consts.Sample.MD5],
                                  'is_bulk_add_objects': True},
                                  RequestContext(request));

@user_passes_test(user_can_view_data)
def upload_file(request):
    """
    Upload a new sample.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :returns: :class:`django.http.HttpResponse`
    """

    if request.method == 'POST':
        form = UploadFileForm(request.user, request.POST, request.FILES)
        email_errmsg = None
        if form.is_valid():
            campaign = form.cleaned_data['campaign']
            confidence = form.cleaned_data['confidence']
            source = form.cleaned_data['source']
            reference = form.cleaned_data['reference']
            try:
                if request.FILES:
                    sample_md5 = handle_uploaded_file(
                        request.FILES['filedata'],
                        source,
                        reference,
                        form.cleaned_data['file_format'],
                        form.cleaned_data['password'],
                        user=request.user.username,
                        campaign=campaign,
                        confidence=confidence,
                        parent_md5 = form.cleaned_data['parent_md5'],
                        bucket_list=form.cleaned_data[form_consts.Common.BUCKET_LIST_VARIABLE_NAME],
                        ticket=form.cleaned_data[form_consts.Common.TICKET_VARIABLE_NAME])
                else:
                    filename = request.POST['filename'].strip()
                    md5 = request.POST['md5'].strip().lower()
                    sample_md5 = handle_uploaded_file(
                        None,
                        source,
                        reference,
                        form.cleaned_data['file_format'],
                        None,
                        user=request.user.username,
                        campaign=campaign,
                        confidence=confidence,
                        parent_md5 = form.cleaned_data['parent_md5'],
                        filename=filename,
                        md5=md5,
                        bucket_list=form.cleaned_data[form_consts.Common.BUCKET_LIST_VARIABLE_NAME],
                        ticket=form.cleaned_data[form_consts.Common.TICKET_VARIABLE_NAME],
                        is_return_only_md5=False)

                if 'email' in request.POST:
                    for s in sample_md5:
                        email_errmsg = mail_sample(s, [request.user.email])
            except ZipFileError, zfe:
                return render_to_response('file_upload_response.html',
                                          {'response': json.dumps({'success': False,
                                                                   'message': zfe.value})},
                                          RequestContext(request))
            else:
                response = {'success': False,
                            'message': 'Unknown error; unable to upload file.'}
                if len(sample_md5) > 1:
                    filedata = request.FILES['filedata']
                    message = ('<a href="%s">View Uploaded Samples.</a>'
                               % reverse('crits.samples.views.view_upload_list',
                                         args=[filedata.name, sample_md5]))
                    response = {'success': True,
                                'message': message }
                elif len(sample_md5) == 1:
                    md5_response = None
                    if not request.FILES:
                        response['success'] = sample_md5[0].get('success', False)
                        if(response['success'] == False):
                            response['message'] = sample_md5[0].get('message', response.get('message'))
                        else:
                            md5_response = sample_md5[0].get('object').md5
                    else:
                        md5_response = sample_md5[0]
                        response['success'] = True

                    if md5_response != None:
                        response['message'] = ('File uploaded successfully. <a href="%s">View Sample.</a>'
                                               % reverse('crits.samples.views.detail',
                                                         args=[md5_response]))

                if email_errmsg is not None:
                    msg = "<br>Error sending email: %s" % email_errmsg
                    response['message'] = response['message'] + msg

                return render_to_response("file_upload_response.html",
                                          {'response': json.dumps(response)},
                                          RequestContext(request))
        else:
            return render_to_response('file_upload_response.html',
                                      {'response': json.dumps({'success': False,
                                                               'form': form.as_table()})},
                                      RequestContext(request))

#TODO
@user_passes_test(user_can_view_data)
def upload_child(request, parent_md5):
    """
    Upload a new child sample.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param parent_md5: The MD5 of the parent sample.
    :type parent_md5: str
    :returns: :class:`django.http.HttpResponse`
    """

    new_samples = []
    if request.method == "POST":
        form = EmailAttachForm(request.user.username, request.POST, request.FILES)
        if form.is_valid():
            if request.FILES or 'filename' in request.POST and 'md5' in request.POST:
                # Child samples inherit all of the sources of the parent.
                parent = Sample.objects(md5=parent_md5).first()
                if not parent:
                    return render_to_response('error.html',
                                              {'error': "Unable to find parent."},
                                              RequestContext(request))
                source = parent.source

                campaign_name = request.POST['campaign']
                confidence = request.POST['confidence']
                parent.campaign.append(EmbeddedCampaign(name=campaign_name, confidence=confidence, analyst=request.user.username))
                campaigns = parent.campaign

                try:
                    if request.FILES:
                        new_samples = handle_uploaded_file(request.FILES["filedata"],
                                                           source,
                                                           None,
                                                           form.cleaned_data["file_format"],
                                                           form.cleaned_data["password"],
                                                           user=request.user.username,
                                                           campaign=campaigns,
                                                           parent_md5=parent_md5,
                                                           bucket_list=form.cleaned_data[form_consts.Common.BUCKET_LIST_VARIABLE_NAME],
                                                           ticket=form.cleaned_data[form_consts.Common.TICKET_VARIABLE_NAME])
                    else:
                        filename = request.POST['filename'].strip()
                        md5= request.POST['md5'].strip().lower()
                        if not filename or not md5:
                            error = "Need a file, or a filename and an md5."
                            return render_to_response('error.html',
                                                      {'error': error},
                                                      RequestContext(request))
                        else:
                            new_samples = handle_uploaded_file(None,
                                                               source,
                                                               None,
                                                               form.cleaned_data["file_format"],
                                                               form.cleaned_data["password"],
                                                               user=request.user.username,
                                                               campaign=campaigns,
                                                               parent_md5=parent_md5,
                                                               filename=filename,
                                                               bucket_list=form.cleaned_data[form_consts.Common.BUCKET_LIST_VARIABLE_NAME],
                                                               ticket=form.cleaned_data[form_consts.Common.TICKET_VARIABLE_NAME],
                                                               md5=md5)
                except ZipFileError, zfe:
                    return render_to_response('error.html',
                                              {'error': zfe.value},
                                              RequestContext(request))
            else:
                return render_to_response('error.html',
                                          {'error': "Need a file, or a filename and an md5."},
                                          RequestContext(request))
        else:
            return render_to_response('error.html',
                                      {'error': 'form error'},
                                      RequestContext(request))

    # handle_upload_file() returns a list of strings. Use those strings to
    # find the sample and add anything submitted on the form to it.
    results = add_source_to_samples(new_samples,
                                    form.cleaned_data['source'],
                                    form.cleaned_data.get('source_method', 'Upload'),
                                    form.cleaned_data.get('source_reference', None),
                                    request.user.username)
    if not results['success']:
        return render_to_response('error.html',
                                  {'error': results['message']},
                                  RequestContext(request))
    return HttpResponseRedirect(reverse('crits.samples.views.detail',
                                        args=[parent_md5]))

@user_passes_test(user_can_view_data)
def new_exploit(request):
    """
    Upload a new exploit. Should be an AJAX POST.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :returns: :class:`django.http.HttpResponse`
    """

    if request.method == 'POST' and request.is_ajax():
        form = NewExploitForm(request.POST)
        analyst = request.user.username
        if form.is_valid():
            result = add_new_exploit(form.cleaned_data['name'],
                                     analyst)
            if result:
                message = {'message': '<div>Exploit added successfully!</div>',
                           'success':True}
            else:
                message = {'message': '<div>Exploit addition failed!</div>',
                           'success': False}
        else:
            message = {'form':form.as_table(),
                       'success': False}
        return HttpResponse(json.dumps(message),
                            mimetype="application/json")
    return render_to_response("error.html",
                              {'error':'Expected AJAX POST'},
                              RequestContext(request))

@user_passes_test(user_can_view_data)
def new_backdoor(request):
    """
    Upload a new backdoor. Should be an AJAX POST.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :returns: :class:`django.http.HttpResponse`
    """

    if request.method == 'POST' and request.is_ajax():
        form = NewBackdoorForm(request.POST)
        analyst = request.user.username
        if form.is_valid():
            success = add_new_backdoor(form.cleaned_data['name'],
                                       analyst)
            if success:
                message = {'message': '<div>Backdoor added successfully!</div>',
                           'success':True}
            else:
                message = {'message': '<div>Backdoor addition failed!</div>',
                           'success': False,
                           'form':form.as_table()}
        else:
            message = {'form': form.as_table(),
                       'success': False}
        return HttpResponse(json.dumps(message),
                            mimetype="application/json")
    return render_to_response("error.html",
                              {'error':'Expected AJAX POST'},
                              RequestContext(request))

@user_passes_test(user_can_view_data)
def strings(request, sample_md5):
    """
    Generate strings for a sample. Should be an AJAX POST.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param sample_md5: The MD5 of the sample to use.
    :type sample_md5: str
    :returns: :class:`django.http.HttpResponse`
    """

    if request.is_ajax():
        strings_data = make_ascii_strings(md5=sample_md5)
        strings_data += make_unicode_strings(md5=sample_md5)
        result = {"strings": strings_data}
        return HttpResponse(json.dumps(result),
                            mimetype='application/json')
    else:
        return render_to_response('error.html',
                                  {'error': "Expected AJAX."},
                                  RequestContext(request))

@user_passes_test(user_can_view_data)
def stackstrings(request, sample_md5):
    """
    Generate stack strings for a sample. Should be an AJAX POST.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param sample_md5: The MD5 of the sample to use.
    :type sample_md5: str
    :returns: :class:`django.http.HttpResponse`
    """

    if request.is_ajax():
        strings = make_stackstrings(md5=sample_md5)
        result = {"strings": strings}
        return HttpResponse(json.dumps(result),
                            mimetype='application/json')
    else:
        return render_to_response('error.html',
                                  {'error': "Expected AJAX."},
                                  RequestContext(request))

@user_passes_test(user_can_view_data)
def hex(request,sample_md5):
    """
    Generate hex for a sample. Should be an AJAX POST.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param sample_md5: The MD5 of the sample to use.
    :type sample_md5: str
    :returns: :class:`django.http.HttpResponse`
    """

    if request.is_ajax():
        hex_data = make_hex(md5=sample_md5)
        result = {"strings": hex_data}
        return HttpResponse(json.dumps(result),
                            mimetype='application/json')
    else:
        return render_to_response('error.html',
                                  {'error': "Expected AJAX."},
                                  RequestContext(request))

@user_passes_test(user_can_view_data)
def xor(request,sample_md5):
    """
    Generate xor results for a sample. Should be an AJAX POST.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param sample_md5: The MD5 of the sample to use.
    :type sample_md5: str
    :returns: :class:`django.http.HttpResponse`
    """

    if request.is_ajax():
        key = request.GET.get('key')
        key = int(key)
        xor_data = xor_string(md5=sample_md5,
                              key=key)
        xor_data = make_ascii_strings(data=xor_data)
        result = {"strings": xor_data}
        return HttpResponse(json.dumps(result),
                            mimetype='application/json')
    else:
        return render_to_response('error.html',
                                  {'error': "Expected AJAX."},
                                  RequestContext(request))

@user_passes_test(user_can_view_data)
def xor_searcher(request, sample_md5):
    """
    Generate xor search results for a sample. Should be an AJAX POST.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param sample_md5: The MD5 of the sample to use.
    :type sample_md5: str
    :returns: :class:`django.http.HttpResponse`
    """

    if request.method == "POST" and request.is_ajax():
        form = XORSearchForm(request.POST)
        if form.is_valid():
            try:
                string = request.POST['string']
            except:
                string = None
            try:
                if request.POST["skip_nulls"] == "on":
                    skip_nulls = 1
            except:
                skip_nulls = 0
            try:
                if request.POST["is_key"] == "on":
                    is_key = 1
            except:
                is_key = 0
            if is_key:
                try:
                    result = {"keys": [int(string)]}
                except:
                    result = {"keys": []}
            else:
                results = xor_search(md5=sample_md5,
                                    string=string,
                                     skip_nulls=skip_nulls)
                result = {"keys": results}
            return HttpResponse(json.dumps(result),
                                mimetype='application/json')
        else:
            return render_to_response('error.html',
                                      {'error': "Invalid Form."},
                                      RequestContext(request))
    else:
        return render_to_response('error.html',
                                  {'error': "Expected AJAX POST."},
                                  RequestContext(request))

@user_passes_test(user_can_view_data)
def unzip_sample(request, md5):
    """
    Unzip a sample.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param md5: The MD5 of the sample to use.
    :type md5: str
    :returns: :class:`django.http.HttpResponse`
    """

    if request.method == "POST":
        # Intentionally using UnrarSampleForm here. Both unrar and unzip use
        # the same form because it's an identical form.
        form = UnrarSampleForm(request.POST)
        if form.is_valid():
            pwd = form.cleaned_data['password']
            try:
                handle_unzip_file(md5, user=request.user.username, password=pwd)
            except ZipFileError, zfe:
                return render_to_response('error.html',
                                          {'error' : zfe.value},
                                          RequestContext(request))
        return HttpResponseRedirect(reverse('crits.samples.views.detail',
                                            args=[md5]))
    else:
        return render_to_response('error.html',
                                  {'error': 'Expecting POST.'},
                                  RequestContext(request))

@user_passes_test(user_can_view_data)
def unrar_sample(request, md5):
    """
    Unrar a sample.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param md5: The MD5 of the sample to use.
    :type md5: str
    :returns: :class:`django.http.HttpResponse`
    """

    if request.method == "POST":
        unrar_form = UnrarSampleForm(request.POST)
        if unrar_form.is_valid():
            pwd = unrar_form.cleaned_data['password']
            try:
                handle_unrar_sample(md5, user=request.user.username, password=pwd)
            except ZipFileError, zfe:
                return render_to_response('error.html',
                                          {'error' : zfe.value},
                                          RequestContext(request))
        return HttpResponseRedirect(reverse('crits.samples.views.detail',
                                            args=[md5]))

#TODO: convert to jtable
@user_passes_test(user_can_view_data)
def sources(request):
    """
    Get the sources list for samples.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :returns: :class:`django.http.HttpResponse`
    """

    refresh = request.GET.get("refresh", "no")
    if refresh == "yes":
        generate_sources()
    sources_list = get_source_counts(request.user)
    return render_to_response('samples_sources.html',
                              {'sources': sources_list},
                              RequestContext(request))

#TODO: convert to jtable
@user_passes_test(user_can_view_data)
def exploit(request):
    """
    Get the exploits list for samples.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :returns: :class:`django.http.HttpResponse`
    """

    refresh = request.GET.get("refresh", "no")
    if refresh == "yes":
        generate_exploits()
    exploit_list = get_exploits()
    return render_to_response('samples_exploit.html',
                              {'exploits': exploit_list},
                              RequestContext(request))

@user_passes_test(user_can_view_data)
def add_exploit(request, sample_md5):
    """
    Add an exploit to a sample.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param sample_md5: The MD5 of the sample to add to.
    :type sample_md5: str
    :returns: :class:`django.http.HttpResponse`
    """

    if request.method == "POST":
        exploit_form = ExploitForm(request.POST)
        if exploit_form.is_valid():
            cve = exploit_form.cleaned_data['exploit']
            analyst = request.user.username
            add_exploit_to_sample(sample_md5,
                                  cve.upper(),
                                  analyst)
    return HttpResponseRedirect(reverse('crits.samples.views.detail',
                                        args=[sample_md5]))

@user_passes_test(user_can_view_data)
def add_backdoor(request, sample_md5):
    """
    Add a backdoor to a sample.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param sample_md5: The MD5 of the sample to add to.
    :type sample_md5: str
    :returns: :class:`django.http.HttpResponse`
    """

    if request.method == "POST":
        backdoor_form = BackdoorForm(request.POST)
        if backdoor_form.is_valid():
            name = backdoor_form.cleaned_data['backdoor_types']
            version = backdoor_form.cleaned_data['backdoor_version']
            analyst = request.user.username
            add_backdoor_to_sample(sample_md5,
                                   name,
                                   version,
                                   analyst)
    return HttpResponseRedirect(reverse('crits.samples.views.detail',
                                        args=[sample_md5]))

@user_passes_test(user_is_admin)
def remove_sample(request, md5):
    """
    Remove a sample from CRITs.

    :param request: Django request object (Required)
    :type request: :class:`django.http.HttpRequest`
    :param md5: The MD5 of the sample to remove.
    :type md5: str
    :returns: :class:`django.http.HttpResponse`
    """

    result = delete_sample(md5, '%s' % request.user.username)
    if result:
        org = get_user_organization(request.user.username)
        return HttpResponseRedirect(reverse('crits.samples.views.samples_listing')
                                    +'?source=%s' % org)
    else:
        return render_to_response('error.html',
                                  {'error': "Could not delete sample"},
                                  RequestContext(request))
