#!/usr/bin/env perl
use strict;
use warnings;
use JSON::PP qw(decode_json);
die "Usage: $0 NaturalEarth.geojson NEW_OUTPUT_DIR\n" unless @ARGV==2;
open my $fh,'<',$ARGV[0] or die $!;local $/;my $j=decode_json(<$fh>);close $fh;
for my $country(qw(USA CAN)) {
 my @matches=grep {($_->{properties}{ADM0_A3}//'') eq $country} @{$j->{features}};
 die "Expected one geometry for $country\n" unless @matches==1;
 my $g=$matches[0]{geometry};die "Expected MultiPolygon\n" unless $g->{type} eq 'MultiPolygon';
 my @rings=map {@$_} @{$g->{coordinates}};
 my $path="$ARGV[1]/$country.polygons";die "Refuse overwrite $path\n" if -e $path;
 open my $out,'>',$path or die $!;print $out scalar(@rings),"\n";
 for my $ring(@rings) {
  print $out scalar(@$ring),"\n";
  for my $p(@$ring) {die "Malformed coordinate\n" unless @$p>=2;printf $out "%.12g %.12g\n",@$p[0,1];}
 }
 close $out or die $!;print "$country rings=",scalar(@rings)," file=$path\n";
}
