{#
    Normalisation des constructeurs TOP500 — deux macros complémentaires :

    * normalize_vendor(col) : clé de jointure avec le seed vendor_mapping
      (minuscules, espaces multiples réduits). « Bull SAS » -> « bull sas ».

    * primary_vendor(col) : premier constructeur d'un libellé composé.
      « HPE, GALAXY » -> « HPE », « NEC/Lenovo » -> « NEC »,
      « ASUSTeK / Taiwan AI Cloud / Taiwan Mobile » -> « ASUSTeK ».
      Convention : le premier nommé est le maître d'œuvre (documentée dans le README).

    Le regroupement métier (Bull / Atos / Eviden -> Bull) reste dans le seed :
    il est auditable et modifiable sans toucher au SQL.
#}

{% macro normalize_vendor(column) -%}
    lower(regexp_replace(trim({{ column }}), '\s+', ' ', 'g'))
{%- endmacro %}

{% macro primary_vendor(column) -%}
    trim(regexp_replace(trim({{ column }}), '\s*[/,].*$', ''))
{%- endmacro %}
