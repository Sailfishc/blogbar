# coding: utf-8
import sys
import os
import jinja2
import hashlib
from flask import Flask, request, url_for, g, render_template, abort
from flask_wtf.csrf import CsrfProtect
from flask.ext.uploads import configure_uploads
from flask_debugtoolbar import DebugToolbarExtension
from werkzeug.wsgi import SharedDataMiddleware
from werkzeug.contrib.fixers import ProxyFix
from .utils.account import get_current_user
from six import iteritems

# 将project目录加入sys.path
project_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_path not in sys.path:
    sys.path.insert(0, project_path)

from config import load_config

# convert python's encoding to utf8
reload(sys)
sys.setdefaultencoding('utf8')


def create_app():
    """创建Flask app"""
    app = Flask(__name__)

    config = load_config()
    app.config.from_object(config)

    # Proxy fix
    app.wsgi_app = ProxyFix(app.wsgi_app)

    # CSRF protect
    CsrfProtect(app)

    if app.debug:
        DebugToolbarExtension(app)

        # serve static files during development
        app.wsgi_app = SharedDataMiddleware(app.wsgi_app, {
            '/uploads': os.path.join(app.config.get('PROJECT_PATH'), 'uploads')
        })
    else:
        from .utils.sentry import sentry

        sentry.init_app(app, dsn=app.config.get('SENTRY_DSN'))

    # 注册组件
    register_db(app)
    register_routes(app)
    register_jinja(app)
    register_error_handle(app)
    register_uploadsets(app)

    # before every request
    @app.before_request
    def before_request():
        ban_ips = app.config.get('BAN_IPS')
        if request.remote_addr in ban_ips:
            abort(404)
        g.user = get_current_user()

    return app


def register_jinja(app):
    """注册模板全局变量和全局函数"""
    from jinja2 import Markup
    from .utils import filters
    from .utils import permissions

    app.jinja_env.filters['timesince'] = filters.timesince
    app.jinja_env.filters['get_keywords'] = filters.get_keywords
    app.jinja_env.filters['readtime'] = filters.readtime
    app.jinja_env.filters['friendly_url'] = filters.friendly_url
    app.jinja_env.filters['clean_url'] = filters.clean_url

    my_loader = jinja2.ChoiceLoader([
        app.jinja_loader,
        jinja2.FileSystemLoader([os.path.join(app.config.get('PROJECT_PATH'), 'application/macros')]),
    ])
    app.jinja_loader = my_loader

    if not hasattr(app, '_static_hash'):
        app._static_hash = {}

    # inject vars into template context
    @app.context_processor
    def inject_vars():
        from .utils.permissions import AdminPermission
        from .models import db, ApprovementLog, Post, UserReadPost

        new_blogs_count = 0
        if AdminPermission().check():
            new_blogs_count = ApprovementLog.query.filter(ApprovementLog.status == -1).count()

        new_posts_count = 0
        if g.user:
            new_posts_count = UserReadPost.query. \
                filter(UserReadPost.user_id == g.user.id). \
                filter(UserReadPost.post.has(~Post.hide)). \
                filter(UserReadPost.unread).count()

        return dict(
            new_blogs_count=new_blogs_count,
            new_posts_count=new_posts_count
        )

    def url_for_other_page(page):
        """Generate url for pagination"""
        view_args = request.view_args.copy()
        args = request.args.copy().to_dict()
        combined_args = dict(view_args.items() + args.items())
        combined_args['page'] = page
        return url_for(request.endpoint, **combined_args)

    def static(filename):
        """静态资源url

        计算资源内容hash作为query string，并缓存起来。
        """
        if app.testing:
            return url_for('static', filename=filename)

        if filename in app._static_hash:
            return app._static_hash[filename]

        path = os.path.join(app.static_folder, filename)
        if not os.path.exists(path):
            return url_for('static', filename=filename)

        with open(path, 'r') as f:
            content = f.read()
            hash = hashlib.md5(content).hexdigest()

        url = '%s?v=%s' % (url_for('static', filename=filename), hash[:10])
        app._static_hash[filename] = url
        return url

    def script(path):
        """script标签"""
        return Markup("<script type='text/javascript' src='%s'></script>" % static(path))

    def link(path):
        """link标签"""
        return Markup("<link rel='stylesheet' href='%s'>" % static(path))

    def page_script(template_reference):
        """单页script标签"""
        template_name = _get_template_name(template_reference)
        return script('js/%s' % template_name.replace('html', 'js'))

    def page_link(template_reference):
        """单页link标签"""
        template_name = _get_template_name(template_reference)
        return link('css/%s' % template_name.replace('html', 'css'))

    def page_name(template_reference):
        template_name = _get_template_name(template_reference)
        return "page-%s" % template_name.replace('.html', '').replace('/', '-').replace('_', '-')

    rules = {}
    for endpoint, _rules in iteritems(app.url_map._rules_by_endpoint):
        if any(item in endpoint for item in ['_debug_toolbar', 'debugtoolbar', 'static']):
            continue
        rules[endpoint] = [{'rule': rule.rule} for rule in _rules]

    app.jinja_env.globals['url_for_other_page'] = url_for_other_page
    app.jinja_env.globals['static'] = static
    app.jinja_env.globals['script'] = script
    app.jinja_env.globals['page_script'] = page_script
    app.jinja_env.globals['link'] = link
    app.jinja_env.globals['page_link'] = page_link
    app.jinja_env.globals['page_name'] = page_name
    app.jinja_env.globals['permissions'] = permissions
    app.jinja_env.globals['rules'] = rules


def register_db(app):
    """注册Model"""
    from .models import db

    db.init_app(app)


def register_routes(app):
    """注册路由"""
    from .controllers import site, blog, admin, account

    app.register_blueprint(site.bp, url_prefix='')
    app.register_blueprint(blog.bp, url_prefix='/blog')
    app.register_blueprint(account.bp, url_prefix='/account')
    app.register_blueprint(admin.bp, url_prefix='/admin')


def register_error_handle(app):
    """注册HTTP错误页面"""

    @app.errorhandler(403)
    def page_403(error):
        return render_template('site/403.html'), 403

    @app.errorhandler(404)
    def page_404(error):
        return render_template('site/404.html'), 404

    @app.errorhandler(500)
    def page_500(error):
        return render_template('site/500.html'), 500


def register_uploadsets(app):
    """注册UploadSets"""
    from .utils.uploadsets import avatars

    configure_uploads(app, (avatars))


def _get_template_name(template_reference):
    """获取当前模板名"""
    return template_reference._TemplateReference__context.name
