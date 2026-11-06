{#
    Par défaut dbt crée « <schema_cible>_<schema_custom> » (ex. public_marts).
    On veut des schémas propres (staging, intermediate, marts) qui correspondent
    à ceux créés et sécurisés dans infra/postgres/init.sql.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
