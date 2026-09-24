// reconstructed SCAD — BambuLab Toolbox. No original source recovered.
/* [Parameters] */
base_color = "#E9C7DA"; // color
part_2 = "LUNA";
part_2_font = "Roboto"; // font
part_2_size = 12.0; // [0.1:0.1:1000]
part_2_height = 1.2000000000000002; // [0.1:0.1:1000]
part_2_spacing = 1.0; // [0.1:0.1:10]
part_2_color = "#FFFFFF"; // color
part_2_x = 27.0;
part_2_y = 10.8;
part_2_z = 3.0;
part_2_rx = 0.0;
part_2_ry = 0.0;
part_2_rz = 0.0;
part_2_halign = "center"; // [left, center, right]
part_2_valign = "center"; // [top, center, baseline, bottom]
/* [Hidden] */
$fn = 64;
module core_model() {
  translate([0.0, 0.0, 0.0]) color(base_color) import("assets/51239827a65371b94cf006e7df58f38e6e66d0911df7dbf6724f42c9f9d2f71b.stl");
  translate([part_2_x,part_2_y,part_2_z])
  rotate([part_2_rx,part_2_ry,part_2_rz])
  color(base_color) linear_extrude(height=part_2_height)
  text(part_2,font=part_2_font,size=part_2_size,halign=part_2_halign,valign=part_2_valign,spacing=part_2_spacing);
}
core_model();
