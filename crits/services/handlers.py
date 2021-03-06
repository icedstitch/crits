import datetime

from django.conf import settings

import crits.service_env

from crits.core.class_mapper import class_from_type
from crits.core.crits_mongoengine import EmbeddedAnalysisResult
from crits.core.user_tools import user_sources
from crits.services.contexts import CertificateContext, DomainContext
from crits.services.contexts import EventContext, IndicatorContext, IPContext
from crits.services.contexts import PCAPContext, RawDataContext, SampleContext


def get_context(user, data, obj):
    """
    Create a context based on the supplied information.

    :param user: The user creating the context.
    :type user: str
    :param data: The data to seed the context.
    :type data: str
    :param obj: The CRITs top-level object class.
    :type obj: Class which inherits from
               :class:`crits.core.crits_mongoengine.CritsBaseAttributes`
    :returns: :class:`crits.services.core.Context`
    """

    type_ = obj._meta['crits_type']
    if type_ == 'Certificate':
        return CertificateContext(user, data, obj.md5, obj.to_dict())
    if type_ == 'Domain':
        return DomainContext(user, obj.id, obj.to_dict())
    if type_ == 'Event':
        return EventContext(user, obj.id, obj.to_dict())
    if type_ == 'Indicator':
        return IndicatorContext(user, obj.id, obj.to_dict())
    if type_ == 'IP':
        return IPContext(user, obj.id, obj.to_dict())
    if type_ == 'PCAP':
        return PCAPContext(user, data, obj.md5, obj.to_dict())
    if type_ == 'RawData':
        return RawDataContext(user, obj.id, obj.to_dict())
    if type_ == 'Sample':
        return SampleContext(user, data, obj.md5, obj.to_dict())


def run_triage(data, obj, user):
    """
    Run all services marked as triage against this top-level object.

    :param data: The data to seed the context.
    :type data: str
    :param obj: The CRITs top-level object class.
    :type obj: Class which inherits from
               :class:`crits.core.crits_mongoengine.CritsBaseAttributes`
    :param user: The user requesting the services to be run.
    :type user: str
    """

    env = crits.service_env.environment
    try:
        context = get_context(user, data, obj)
    except:
        return
    for service_name in env.manager.triage_services:
        try:
            env.run_service(service_name, context,
                            execute=settings.SERVICE_MODEL)
        except:
            pass
    return


def add_result(object_type, object_id, analysis_id, result, type_, subtype,
               analyst):
    """
    Add a result to an analysis task.

    :param object_type: The top-level object type.
    :type object_type: str
    :param object_id: The ObjectId to search for.
    :type object_id: str
    :param analysis_id: The ID of the task to update.
    :type analysis_id: str
    :param result: The result to append.
    :type result: str
    :param type_: The result type.
    :type type_: str
    :param subtype: The result subtype.
    :type subtype: str
    :param analyst: The user updating the results.
    :type analyst: str
    :returns: dict with keys "success" (boolean) and "message" (str) if failed.
    """

    res = {'success': False}
    if not object_type or not object_id or not analysis_id:
        res['message'] = "Must supply object id/type and analysis id."
        return res
    klass = class_from_type(object_type)
    sources = user_sources(analyst)
    obj = klass.objects(id=object_id, source__name__in=sources).first()
    if not obj:
        res['message'] = "Could not find object to add results to."
        return res
    found = False
    c = 0
    for a in obj.analysis:
        if str(a.analysis_id) == analysis_id:
            found = True
            break
        c += 1
    if not found:
        res['message'] = "Could not find an analysis task to update."
        return res
    if result and type_ and subtype:
        result = {'result': result, 'Type': type_, 'subtype': subtype}
        klass.objects(id=object_id,
                        analysis__id=analysis_id).update_one(push__analysis__S__results=result)
    else:
        res['message'] = "Need a result, type, and subtype to add a result."
        return res
    res['success'] = True
    return res


def add_log(object_type, object_id, analysis_id, log_message, level, analyst):
    """
    Add a log entry to an analysis task.

    :param object_type: The top-level object type.
    :type object_type: str
    :param object_id: The ObjectId to search for.
    :type object_id: str
    :param analysis_id: The ID of the task to update.
    :type analysis_id: str
    :param log_message: The log entry to append.
    :type log_message: dict
    :param level: The log level.
    :type level: str
    :param analyst: The user updating the log.
    :type analyst: str
    :returns: dict with keys "success" (boolean) and "message" (str) if failed.
    """

    results = {'success': False}
    if not object_type or not object_id or not analysis_id:
        results['message'] = "Must supply object id/type and analysis id."
        return results
    klass = class_from_type(object_type)
    sources = user_sources(analyst)
    obj = klass.objects(id=object_id, source__name__in=sources).first()
    if not obj:
        results['message'] = "Could not find object to add log to."
        return results
    found = False
    c = 0
    for a in obj.analysis:
        if str(a.analysis_id) == analysis_id:
            found = True
            break
        c += 1
    if not found:
        results['message'] = "Could not find an analysis task to update."
        return results
    le = EmbeddedAnalysisResult.EmbeddedAnalysisResultLog()
    le.message = log_message
    le.level = level
    le.datetime = str(datetime.datetime.now())
    klass.objects(id=object_id,
                  analysis__id=analysis_id).update_one(push__analysis__S__log=le)
    results['success'] = True
    return results


def finish_task(object_type, object_id, analysis_id, status, analyst):
    """
    Finish a task by setting its status to "completed" and setting the finish
    date.

    :param object_type: The top-level object type.
    :type object_type: str
    :param object_id: The ObjectId to search for.
    :type object_id: str
    :param analysis_id: The ID of the task to update.
    :type analysis_id: str
    :param status: The status of the task.
    :type status: str ("error", "completed")
    :param analyst: The user updating the log.
    :type analyst: str
    :returns: dict with keys "success" (boolean) and "message" (str) if failed.
    """

    results = {'success': False}
    if not status:
        status = "completed"
    if status not in ('error', 'completed'):
        status = "completed"
    if not object_type or not object_id or not analysis_id:
        results['message'] = "Must supply object id/type and analysis id."
        return results
    klass = class_from_type(object_type)
    sources = user_sources(analyst)
    obj = klass.objects(id=object_id, source__name__in=sources).first()
    if not obj:
        results['message'] = "Could not find object to add log to."
        return results
    date = str(datetime.datetime.now())
    klass.objects(id=object_id,
                  analysis__id=analysis_id).update_one(set__analysis__S__status=status,
                                                       set__analysis__S__finish_date=date)
    results['success'] = True
    return results
