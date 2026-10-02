#!/usr/bin/env perl
# Summarize raw aggregate discrepancies; never normalizes origin states.
use strict;
use warnings;
my $path=shift @ARGV or die "Usage: $0 GC.log\n";
open my $fh,'<',$path or die "$path: $!";
my (%seen,%stats,%previous);my $rows=0;
print join("\t",qw(row operator parent units parent_kg signed_residual_kg L1_residual_kg max_cell_residual_kg arctic_L1_kg USA_kg CAN_kg ROW_kg UNT_kg relative_L1 delta_signed_kg delta_L1_kg)),"\n";
while(my $line=<$fh>) {
 next unless $line=~/^BRC_ORIGIN_AUDIT\s+(\w+)\s+(\w+)\s+(\d+)\s+(.*)$/;
 my ($op,$p,$unit,$tail)=($1,$2,$3,$4);my @v=split /\s+/,$tail;
 die "Malformed audit record\n" unless @v==9;
 for(@v){die "Nonfinite audit record\n" unless /^[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?$/;s/[Dd]/e/;$_+=0;}
 my($mass,$signed,$l1,$max,$arctic,@origins)=@v;
 die "Negative magnitude/origin mass\n" if $mass<0||$l1<0||$max<0||$arctic<0||grep {$_<0} @origins;
 my $sum=0;$sum+=$_ for @origins;
 die "Printed mass accounting inconsistent\n" if abs($sum-$mass-$signed)>5e-12*($mass+1)||abs($signed)>$l1+5e-12*($mass+1);
 my $rel=$mass>0?$l1/$mass:($l1==0?0:1e300);
 my ($ds,$dl)=(0,0);if($previous{$p}){$ds=$signed-$previous{$p}[0];$dl=$l1-$previous{$p}[1];}
 $previous{$p}=[$signed,$l1];$seen{$op}{$p}++;$rows++;
 print join("\t",$rows,$op,$p,$unit,@v,$rel,$ds,$dl),"\n";
 $stats{$p}{max_relative_L1}=$rel if !defined($stats{$p}{max_relative_L1})||$rel>$stats{$p}{max_relative_L1};
 $stats{$p}{max_arctic_L1}=$arctic if !defined($stats{$p}{max_arctic_L1})||$arctic>$stats{$p}{max_arctic_L1};
 $stats{$p}{last}=\@v;
}
close $fh;
for my $op(qw(before_transport transport mixing convection chemistry wetdep)) {
 for my $p(qw(FSOAP FSOAS BRCSOA NPBRCPOA WTC PBRCPOA DBRCPOA)){die "Missing $op/$p audit\n" unless $seen{$op}{$p};}
}
for my $p(sort keys %stats){printf STDERR "%s max_relative_L1=%.8g max_arctic_L1_kg=%.8g final_origin_kg=%s\n",$p,$stats{$p}{max_relative_L1},$stats{$p}{max_arctic_L1},join(',',@{$stats{$p}{last}}[5..8]);}
print STDERR "PASS raw operator audit records=$rows; attribution accuracy requires an external effect/error budget\n";
