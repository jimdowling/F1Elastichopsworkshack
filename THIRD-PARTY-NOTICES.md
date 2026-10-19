# Third-party notices

The generated application uses React / React DOM, Three.js (including OrbitControls), Lucide icons, Vite, Inter, and Space Grotesk. Bundled font and frontend-library license texts are in `licenses/`. Python dependencies retain their respective upstream licenses; they are installed separately, not vendored into this archive.

- React / React DOM: https://react.dev/ — MIT
- Lucide: https://lucide.dev/ — see the bundled license
- Three.js 0.180.0 and OrbitControls: https://threejs.org/ — MIT; `licenses/three-LICENSE.txt`
- Vite: https://vite.dev/ — MIT
- Inter: https://rsms.me/inter/ — SIL Open Font License
- Space Grotesk: https://github.com/floriankarsten/space-grotesk — SIL Open Font License
- pandas: https://pandas.pydata.org/
- NumPy: https://numpy.org/
- scikit-learn: https://scikit-learn.org/
- FastAPI: https://fastapi.tiangolo.com/

Race-data availability and rights are separate from software licenses. See `DATA-NOTICE.md`.

The 3D cars, road, scenery and textures are procedural work in this project. Engine audio is synthesized locally with browser Web Audio; no third-party car CAD, sound samples or official racing recordings are bundled.

## Dashboard reference and public data

https://app.formula1dashboard.com/ informed the dashboard's feature inventory and information architecture. The Pitlane design, implementation, computed summaries and procedural visuals are original; no proprietary source, official car/driver imagery, opaque scores or current-season results were copied.

The two-season archive uses public OpenF1 and Jolpica observations, separately attributed and checksummed in `data/dashboard/manifest.json`. Schema field names align with the organizer's published participant guide; no event-cluster records or credentials are included. Data availability is not a grant of unrestricted redistribution or commercial rights. See `DATA-NOTICE.md` and `docs/DASHBOARD-GUIDE.md`.

## Optional runtime SDK

Hopsworks/HSFS is installed separately through `requirements-integrations.txt`, not vendored into the package. Version 5.2.1 was imported/API-shape checked for this build; no live provider account was accessed. SDK licenses and deployment compatibility remain those of the upstream provider. The event-table source reader uses the same Hopsworks SDK (filtered feature-group reads); no other provider client is used.

## Multi-car replay additions

The 20-driver replay uses additional public OpenF1 location/car-data observations for session 9582, with URLs and digests in `data/replay/manifest.json`. The data is reduced-cadence observed telemetry, not generated race positions. Multi-car scene geometry/liveries remain original procedural illustrations, using the existing Three.js dependency. No official car models, track survey, liveries or engine recordings are bundled.
