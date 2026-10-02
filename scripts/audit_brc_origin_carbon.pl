#!/usr/bin/env perl
# Family closure bounds, never per-country attribution accuracy.
use strict;
use warnings;
my ($log,$csv,$omoc)=@ARGV;
die "Usage: $0 GC.log SIGNED_NET_LOSS.csv OMOC_BBOA\n" unless defined($omoc)&&$omoc=~/^\d+(?:\.\d+)?$/&&$omoc>0;
my @parents=qw(FSOAP FSOAS BRCSOA NPBRCPOA WTC PBRCPOA DBRCPOA);
my %origins=map {$_=>0} qw(USA CAN ROW);
my %seen;
open my $source,'<',$csv or die "$csv: $!";
while(<$source>){chomp;my @v=split /,/;next unless @v==7&&$v[0] eq 'fire_emission'&&exists $origins{$v[2]};
 die "Duplicate selected source\n" if $seen{"$v[1]/$v[2]"}++;
 die "Unexpected source species\n" unless $v[1]=~/^(FSOAP|NPBRCPOA|PBRCPOA|DBRCPOA)$/;
 die "Invalid emitted carbon scale\n" unless $v[5]=~/^[+]?(?:\d+\.?\d*|\.\d+)(?:[Ee][-+]?\d+)?$/;
 $origins{$v[2]}+=$v[5];
}
close $source;
die "Missing selected source fields\n" unless keys(%seen)==12;
my $emitted=0;$emitted+=$_ for values %origins;
die "Zero emitted-carbon scale\n" unless $emitted>0;
open my $fh,'<',$log or die "$log: $!";
my ($position,$group,$label)=(0,0,'');my @sum=(0)x8;my $max=0;my $final;
print "group,operator,parent_carbon_kg,signed_family_residual_kg,family_L1_upper_bound_kg,arctic_L1_upper_bound_kg,USA_carbon_kg,CAN_carbon_kg,ROW_carbon_kg,UNT_carbon_kg,upper_bound_over_final_selected_emitted_carbon_scale\n";
while(<$fh>){next unless /^BRC_ORIGIN_AUDIT\s+(\w+)\s+(\w+)\s+\d+\s+(.*)$/;my ($op,$parent,$tail)=($1,$2,$3);
 die "Incomplete/misordered family audit\n" unless $parent eq $parents[$position]&&(!$position||$op eq $label);
 if(!$position){$label=$op;@sum=(0)x8;}
 my @v=split /\s+/,$tail;die "Invalid audit width\n" unless @v==9;
 for(@v){die "Nonfinite audit\n" unless /^[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?$/;s/[Dd]/e/;$_+=0;}
 my $basis=$position<2?1/$omoc:1;
 # Sum species L1 values is an upper bound, not the L1 of a summed cell field.
 my @indices=(0,1,2,4,5,6,7,8);
 for my $i(0..7){$sum[$i]+=$v[$indices[$i]]*$basis;}
 if(++$position==7){$position=0;$group++;my $scaled=$sum[2]/$emitted;$max=$scaled if $scaled>$max;
  print join(',', $group,$label,map {sprintf('%.17g',$_)} (@sum,$scaled)),"\n";
  $final=[@sum,$scaled];
 }
}
close $fh;die "Partial/no family audit\n" if $position||!$group;
print STDERR "PASS groups=$group selected_FINN_emitted_carbon_scale_kg=$emitted max_family_L1_upper_bound_over_scale=$max final_operator=$label final_scaled_bound=$final->[8]; ENGINEERING_ONLY includes UNT/background and species cancellation; not per-country error or validated attribution\n";
