from vtkmodules.vtkCommonCore import vtkPoints, vtkUnsignedCharArray
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkImageData, vtkPolyData
from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper, vtkTexture

from trame_vtk.modules.vtk.serializers.cache import PROP_CACHE
from trame_vtk.modules.vtk.serializers.initialize import initialize_serializers
from trame_vtk.modules.vtk.serializers.serialize import serialize
from trame_vtk.modules.vtk.serializers.synchronization_context import (
    SynchronizationContext,
)
from trame_vtk.modules.vtk.serializers.utils import reference_id


def _polydata_with_single_vertex():
    polydata = vtkPolyData()
    points = vtkPoints()
    points.InsertNextPoint(0, 0, 0)
    polydata.SetPoints(points)

    verts = vtkCellArray()
    verts.InsertNextCell(1)
    verts.InsertCellPoint(0)
    polydata.SetVerts(verts)
    return polydata


def _property_dependency(actor_state, prop_id):
    return next(
        (
            dep
            for dep in actor_state.get("dependencies", [])
            if dep.get("id") == prop_id
        ),
        None,
    )


def test_visible_actor_discard_clears_property_cache():
    initialize_serializers()
    PROP_CACHE.clear()
    context = SynchronizationContext()

    mapper = vtkPolyDataMapper()
    polydata_with_geometry = _polydata_with_single_vertex()
    mapper.SetInputData(polydata_with_geometry)

    actor = vtkActor()
    actor.SetMapper(mapper)
    actor_id = reference_id(actor)
    prop_id = reference_id(actor.GetProperty())

    initial_state = serialize(None, actor, actor_id, context, 1)
    initial_prop = _property_dependency(initial_state, prop_id)
    assert initial_prop
    assert initial_prop["properties"]

    mapper.SetInputData(vtkPolyData())
    discarded_state = serialize(None, actor, actor_id, context, 1)
    assert discarded_state is None

    mapper.SetInputData(polydata_with_geometry)
    restored_state = serialize(None, actor, actor_id, context, 1)
    restored_prop = _property_dependency(restored_state, prop_id)
    assert restored_prop
    assert restored_prop["properties"]


def test_discarded_visible_actor_does_not_cache_texture_arrays():
    initialize_serializers()
    PROP_CACHE.clear()
    context = SynchronizationContext()

    actor = vtkActor()
    empty_mapper = vtkPolyDataMapper()
    empty_mapper.SetInputData(vtkPolyData())
    actor.SetMapper(empty_mapper)

    image = vtkImageData()
    image.SetDimensions(2, 2, 1)
    scalars = vtkUnsignedCharArray()
    scalars.SetNumberOfComponents(1)
    scalars.SetNumberOfTuples(4)
    for idx in range(4):
        scalars.SetTuple1(idx, idx)
    image.GetPointData().SetScalars(scalars)

    texture = vtkTexture()
    texture.SetInputData(image)
    actor.SetTexture(texture)

    actor_state = serialize(None, actor, reference_id(actor), context, 1)
    assert actor_state is None
    assert len(context.data_array_cache) == 0
