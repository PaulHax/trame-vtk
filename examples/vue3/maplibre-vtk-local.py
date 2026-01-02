"""
MapLibre + VTK Local View Integration Example

This example demonstrates how to use VtkLocalView with an external WebGL context
shared with MapLibre GL JS. VTK renders 3D content over the map.
"""

import asyncio
from urllib.parse import quote as url_quote

from trame.app import get_server
from trame.widgets import vuetify3, vtk as vtk_widgets, html
from trame.ui.vuetify3 import SinglePageLayout

from vtkmodules.vtkFiltersSources import vtkConeSource
from vtkmodules.vtkRenderingCore import (
    vtkRenderer,
    vtkRenderWindow,
    vtkRenderWindowInteractor,
    vtkPolyDataMapper,
    vtkActor,
)

from vtkmodules.vtkInteractionStyle import vtkInteractorStyleSwitch  # noqa
import vtkmodules.vtkRenderingOpenGL2  # noqa

server = get_server()
server.client_type = "vue3"
state, ctrl = server.state, server.controller

state.trame__title = "MapLibre + VTK Local"


renderer = vtkRenderer()
renderer.SetBackground(0, 0, 0)
renderer.SetBackgroundAlpha(0)

renderWindow = vtkRenderWindow()
renderWindow.AddRenderer(renderer)
renderWindow.OffScreenRenderingOn()

renderWindowInteractor = vtkRenderWindowInteractor()
renderWindowInteractor.SetRenderWindow(renderWindow)
renderWindowInteractor.GetInteractorStyle().SetCurrentStyleToTrackballCamera()

cone_source = vtkConeSource()
cone_source.SetHeight(1.0)
cone_source.SetRadius(0.5)
mapper = vtkPolyDataMapper()
actor = vtkActor()
mapper.SetInputConnection(cone_source.GetOutputPort())
actor.SetMapper(mapper)
actor.GetProperty().SetColor(1.0, 0.5, 0.0)
renderer.AddActor(actor)
renderer.ResetCamera()
renderWindow.Render()


@state.change("resolution")
def update_cone(resolution=6, **kwargs):
    cone_source.SetResolution(resolution)
    ctrl.view_update()


async def animate():
    angle = 0
    while True:
        angle = (angle + 0.5) % 360
        actor.SetOrientation(0, angle, 0)
        ctrl.view_update()
        await asyncio.sleep(1 / 60)


ctrl.on_server_ready.add(lambda *args, **kwargs: asyncio.create_task(animate()))


# MapLibre CDN
maplibre_module = {
    "scripts": ["https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"],
    "styles": ["https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css"],
}
server.enable_module(maplibre_module)

# Self-executing init script - defines window.initMapLibreVTK
INIT_SCRIPT_JS = """
(function() {
    let initialized = false;

    window.initMapLibreVTK = async function() {
        if (initialized) return;

        const vtkViewRef = window.trame?.refs?.['vtkView'];
        const vtkView = vtkViewRef?.$.setupState;
        if (!vtkView || !window.maplibregl) {
            setTimeout(window.initMapLibreVTK, 100);
            return;
        }

        initialized = true;

        const map = new maplibregl.Map({
            container: 'map-container',
            style: {
                version: 8,
                sources: {
                    osm: {
                        type: 'raster',
                        tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
                        tileSize: 256,
                        attribution: '© OpenStreetMap contributors'
                    }
                },
                layers: [{
                    id: 'osm',
                    type: 'raster',
                    source: 'osm'
                }]
            },
            center: [-74.5, 40],
            zoom: 9,
            antialias: true
        });

        await new Promise(resolve => map.on('load', resolve));

        const canvas = map.getCanvas();
        const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');

        // Initialize VTK with MapLibre's WebGL context
        vtkView.initializeWithExternalContext(canvas, gl);

        let needsResetCamera = true;

        // Route VTK renders through MapLibre's render cycle
        vtkView.setExternalRenderCallback(() => {
            map.triggerRepaint();
        });

        // MapLibre render callback - do VTK rendering here
        map.on('render', () => {
            try {
                vtkView.saveGLState();
                if (needsResetCamera) {
                    vtkView.resetCamera();
                    needsResetCamera = false;
                }
                vtkView.renderNow();
                vtkView.restoreGLState();
            } catch (e) {
                console.error('VTK render error:', e);
            }
        });
        map.triggerRepaint();
        window.mapLibreMap = map;
        console.log('MapLibre + VTK integration initialized');
    };
})();
"""

# Load the init script after MapLibre
server.enable_module({"scripts": [f"data:text/javascript,{url_quote(INIT_SCRIPT_JS)}"]})



with SinglePageLayout(server) as layout:
    layout.title.set_text("MapLibre + VTK")

    with layout.toolbar:
        vuetify3.VSpacer()
        vuetify3.VSlider(
            density="compact",
            v_model=("resolution", 6),
            min=3,
            max=60,
            step=1,
            hide_details=True,
            label="Resolution",
            style="max-width: 300px",
        )

    with layout.content:
        with vuetify3.VContainer(
            fluid=True,
            classes="pa-0 fill-height",
            style="position: relative;",
        ):
            # MapLibre container - fills the space
            html.Div(
                id="map-container",
                style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;",
            )

            # VTK Local View - hidden, uses MapLibre's WebGL context
            view = vtk_widgets.VtkLocalView(
                renderWindow,
                ref="vtkView",
                style="display: none;",
                on_ready="window.initMapLibreVTK && window.initMapLibreVTK()",
            )
            ctrl.view_update = view.update
            ctrl.view_reset_camera = view.reset_camera


server.start()
