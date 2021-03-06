from typing import Optional, Any, Dict
from collections import OrderedDict
from django.views.generic import TemplateView
from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.template import loader
from django.shortcuts import render

import os
import ujson

from zerver.decorator import has_request_variables, REQ
from zerver.lib import bugdown
from zerver.lib.integrations import CATEGORIES, INTEGRATIONS, HUBOT_LOZENGES
from zerver.lib.subdomains import get_subdomain
from zerver.models import Realm
from zerver.templatetags.app_filters import render_markdown_path

def add_api_uri_context(context, request):
    # type: (Dict[str, Any], HttpRequest) -> None
    subdomain = get_subdomain(request)
    if (subdomain != Realm.SUBDOMAIN_FOR_ROOT_DOMAIN
            or not settings.ROOT_DOMAIN_LANDING_PAGE):
        display_subdomain = subdomain
        html_settings_links = True
    else:
        display_subdomain = 'yourZulipDomain'
        html_settings_links = False
    if display_subdomain != Realm.SUBDOMAIN_FOR_ROOT_DOMAIN:
        external_api_path_subdomain = '%s.%s' % (display_subdomain,
                                                 settings.EXTERNAL_API_PATH)
    else:
        external_api_path_subdomain = settings.EXTERNAL_API_PATH

    external_api_uri_subdomain = '%s%s' % (settings.EXTERNAL_URI_SCHEME,
                                           external_api_path_subdomain)

    context['external_api_path_subdomain'] = external_api_path_subdomain
    context['external_api_uri_subdomain'] = external_api_uri_subdomain
    context["html_settings_links"] = html_settings_links

class ApiURLView(TemplateView):
    def get_context_data(self, **kwargs):
        # type: (**Any) -> Dict[str, str]
        context = super(ApiURLView, self).get_context_data(**kwargs)
        add_api_uri_context(context, self.request)
        return context

class APIView(ApiURLView):
    template_name = 'zerver/api.html'


class HelpView(ApiURLView):
    template_name = 'zerver/help/main.html'
    path_template = 'zerver/help/%s.md'

    def get_path(self, article):
        # type: (str) -> str
        if article == "":
            article = "index"
        elif "/" in article:
            article = "missing"
        return self.path_template % (article,)

    def get_context_data(self, **kwargs):
        # type: (**Any) -> Dict[str, Any]
        article = kwargs["article"]
        context = super(HelpView, self).get_context_data()  # type: Dict[str, Any]
        path = self.get_path(article)
        try:
            loader.get_template(path)
            context["article"] = path
        except loader.TemplateDoesNotExist:
            context["article"] = self.get_path("missing")

        # For disabling the "Back to home" on the homepage
        context["not_index_page"] = not path.endswith("/index.md")
        context["page_is_help_center"] = True
        return context

    def get(self, request, article=""):
        # type: (HttpRequest, str) -> HttpResponse
        path = self.get_path(article)
        result = super(HelpView, self).get(self, article=article)
        try:
            loader.get_template(path)
        except loader.TemplateDoesNotExist:
            # Ensure a 404 response code if no such document
            result.status_code = 404
        if "/" in article:
            result.status_code = 404
        return result


def add_integrations_context(context):
    # type: (Dict[str, Any]) -> None
    alphabetical_sorted_categories = OrderedDict(sorted(CATEGORIES.items()))
    alphabetical_sorted_integration = OrderedDict(sorted(INTEGRATIONS.items()))
    alphabetical_sorted_hubot_lozenges = OrderedDict(sorted(HUBOT_LOZENGES.items()))
    context['categories_dict'] = alphabetical_sorted_categories
    context['integrations_dict'] = alphabetical_sorted_integration
    context['hubot_lozenges_dict'] = alphabetical_sorted_hubot_lozenges

    if "html_settings_links" in context and context["html_settings_links"]:
        settings_html = '<a href="../../#settings">Zulip settings page</a>'
        subscriptions_html = '<a target="_blank" href="../../#streams">streams page</a>'
    else:
        settings_html = 'Zulip settings page'
        subscriptions_html = 'streams page'

    context['settings_html'] = settings_html
    context['subscriptions_html'] = subscriptions_html

    for name in alphabetical_sorted_integration:
        alphabetical_sorted_integration[name].add_doc_context(context)

    for name in alphabetical_sorted_hubot_lozenges:
        alphabetical_sorted_hubot_lozenges[name].add_doc_context(context)


class IntegrationView(ApiURLView):
    template_name = 'zerver/integrations/index.html'

    def get_context_data(self, **kwargs):
        # type: (**Any) -> Dict[str, Any]
        context = super(IntegrationView, self).get_context_data(**kwargs)  # type: Dict[str, Any]
        add_integrations_context(context)
        return context


@has_request_variables
def integration_doc(request, integration_name=REQ(default=None)):
    # type: (HttpRequest, str) -> HttpResponse
    try:
        integration = INTEGRATIONS[integration_name]
    except KeyError:
        return HttpResponseNotFound()

    context = integration.doc_context or {}
    add_integrations_context(context)
    doc_html_str = render_markdown_path(integration.doc, context)

    return HttpResponse(doc_html_str)

def api_endpoint_docs(request):
    # type: (HttpRequest) -> HttpResponse
    context = {}  # type: Dict[str, Any]
    add_api_uri_context(context, request)

    raw_calls = open('templates/zerver/api_content.json', 'r').read()
    calls = ujson.loads(raw_calls)
    langs = set()
    for call in calls:
        call["endpoint"] = "%s/v1/%s" % (context["external_api_uri_subdomain"],
                                         call["endpoint"])
        call["example_request"]["curl"] = call["example_request"]["curl"].replace("https://api.zulip.com",
                                                                                  context["external_api_uri_subdomain"])
        response = call['example_response']
        if '\n' not in response:
            # For 1-line responses, pretty-print them
            extended_response = response.replace(", ", ",\n ")
        else:
            extended_response = response
        call['rendered_response'] = bugdown.convert("~~~ .py\n" + extended_response + "\n~~~\n")
        for example_type in ('request', 'response'):
            for lang in call.get('example_' + example_type, []):
                langs.add(lang)
    return render(
        request,
        'zerver/api_endpoints.html',
        context={'content': calls, 'langs': langs},
    )
