#! python3
"""Select native components by source group, finish, role or stable ID in Rhino 8."""
import Rhino
import rhinoscriptsyntax as rs
import scriptcontext as sc


def main():
    field = rs.GetString('Component property', 'group', ['group', 'finish', 'role', 'component_id'])
    if not field:
        return
    values = sorted({obj.Attributes.GetUserString(field) for obj in sc.doc.Objects
                     if isinstance(obj.Geometry, Rhino.Geometry.Mesh) and obj.Attributes.GetUserString(field)})
    if not values:
        print('No values for property: ' + field)
        return
    value = rs.ListBox(values, 'Select a value', field)
    if value is None:
        return
    sc.doc.Objects.UnselectAll()
    selected = [obj for obj in sc.doc.Objects
                if isinstance(obj.Geometry, Rhino.Geometry.Mesh) and obj.Attributes.GetUserString(field) == value]
    count = sum(1 for obj in selected if obj.Select(True))
    sc.doc.Views.Redraw()
    print('Selected {} mesh components with {} = {}'.format(count, field, value))


if __name__ == '__main__':
    main()
