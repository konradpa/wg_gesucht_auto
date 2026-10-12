# Berlin district data

Provider: Senatsverwaltung für Stadtentwicklung, Bauen und Wohnen Berlin.
Retrieved 2026-10-12. License: Datenlizenz Deutschland – Zero – Version 2.0
(dl-de-zero-2.0), https://www.govdata.de/dl-de/zero-2-0.

Official catalogue:
https://daten.berlin.de/datensaetze/alkis-berlin-bezirke-wfs-ced31d7d

`districts.geojson`: the 12 district geometries from the official WFS
`https://gdi.berlin.de/services/wfs/alkis_bezirke`, layer
`alkis_bezirke:bezirksgrenzen`. Original `namgem` renamed to `name`, other
properties removed; geometries preserved without simplification. WFS 2.0.0
GetFeature, outputFormat=application/json,
srsName=urn:ogc:def:crs:OGC:1.3:CRS84 (longitude, latitude).

`neighborhoods.json`: exact neighborhood names from
`https://gdi.berlin.de/services/wfs/alkis_ortsteile`, layer
`alkis_ortsteile:ortsteile`. `nam` maps to the district identified by the three
district digits `sch[5:8]`, joined to district property `gem`. All 97 returned
features had a matching district.

`neighborhoods.geojson`: geometries from that same cached official Ortsteile
WFS response, retrieved 2026-10-12 in CRS84. `nam` renamed to `name`, district
name joined via the official district code; other properties removed.
All 97 geometries preserved without simplification, including polygon holes
and multipolygons. Used for local coordinate-to-neighborhood lookup.
Official explorer:
https://wfsexplorer.odis-berlin.de/?layer=alkis_ortsteile:ortsteile&wfs=https://gdi.berlin.de/services/wfs/alkis_ortsteile

The data are bundled for local operation; search runs do not query WFS or send
listing addresses to geocoding services. Coordinates supplied by advertisers
may be approximate, so district assignments near boundaries can be imperfect.
